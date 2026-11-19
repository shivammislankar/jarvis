#!/data/data/com.termux/files/usr/bin/python3
"""On-device "Hey Jarvis" wake-word listener (runs on the phone, in Termux).

Reads 16 kHz mono s16le PCM from stdin (fed by parec), runs openWakeWord's on-device
'hey_jarvis' model, and when it fires: records the next few seconds from the same stream,
sends that audio to the Jarvis server for transcription + handling, and speaks the reply.
Audio never leaves the phone until the wake word is detected — before that, nothing is sent.

Pipe the mic in, e.g.:  parec --rate=16000 --channels=1 --format=s16le | jarvis-listen.py
Env: JARVIS_WAKE_THRESHOLD (0-1, default 0.5), JARVIS_CMD_SECS (default 4), JARVIS_TTS=0 to mute.
"""
import io, os, subprocess, sys, time, wave

THRESH = float(os.environ.get("JARVIS_WAKE_THRESHOLD", "0.5"))
CMD_SECS = int(os.environ.get("JARVIS_CMD_SECS", "4"))
HOST = os.environ.get("JARVIS_HOST", "jarvis")
RATE = 16000
FRAME = 1280                                      # 80 ms, openWakeWord's expected chunk


def load_model():
    from openwakeword.model import Model
    err = None
    for fw in ("onnx", "tflite"):
        try:
            return Model(wakeword_models=["hey_jarvis"], inference_framework=fw)
        except Exception as e:
            err = e
    raise RuntimeError(f"could not load openWakeWord ({err})")


def speak(text):
    if os.environ.get("JARVIS_TTS", "1") != "1" or not text:
        return
    opt = []
    cfg = os.path.expanduser("~/.jarvis-tts")
    if os.path.exists(cfg):
        for line in open(cfg):
            k, _, v = line.strip().partition("=")
            v = v.strip()
            if k == "TTS_ENGINE" and v: opt += ["-e", v]
            elif k == "TTS_RATE" and v: opt += ["-r", v]
            elif k == "TTS_PITCH" and v: opt += ["-p", v]
    try: subprocess.run(["termux-tts-speak", *opt, text], timeout=120)
    except Exception: pass


def wav_bytes(pcm):
    b = io.BytesIO(); w = wave.open(b, "wb")
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(pcm); w.close()
    return b.getvalue()


def handle_command(pcm):
    """Send recorded command audio to the server; speak the reply."""
    try:
        p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                            "~/jarvis/bin/voice"], input=wav_bytes(pcm), capture_output=True, timeout=120)
    except Exception as e:
        speak("I couldn't reach the server."); print(f"[server error] {e}", flush=True); return
    out = p.stdout.decode("utf-8", "replace").splitlines()
    heard = next((l[7:] for l in out if l.startswith("heard: ")), "")
    kind = next((l[6:] for l in out if l.startswith("kind: ")), "")
    reply = "\n".join(l for l in out[2:] if not l.startswith("remind: "))
    print(f"› {heard}  [{kind}]\n{reply}", flush=True)
    if kind == "plan":                               # never auto-runs actions hands-free
        speak("I can do that, but open the app to confirm it."); return
    speak(reply)


def main():
    import numpy as np
    try:
        oww = load_model()
    except Exception as e:
        print(f"[fatal] {e}", flush=True); sys.exit(1)
    print(f"Listening for 'Hey Jarvis' (threshold {THRESH}). Nothing is sent until it fires.", flush=True)
    stdin = sys.stdin.buffer
    cooldown = 0
    while True:
        buf = stdin.read(FRAME * 2)
        if len(buf) < FRAME * 2:
            break
        if time.time() < cooldown:
            continue
        audio = np.frombuffer(buf, dtype=np.int16)
        score = oww.predict(audio).get("hey_jarvis", 0)
        if score >= THRESH:
            try: subprocess.run(["termux-vibrate", "-d", "80"], timeout=3)
            except Exception: pass
            speak("Yes?")
            pcm = stdin.read(RATE * 2 * CMD_SECS)      # the command, from the same live stream
            handle_command(pcm)
            oww.reset()                                 # clear history so it doesn't retrigger
            cooldown = time.time() + 1.5
    print("[stream ended]", flush=True)


if __name__ == "__main__":
    main()
