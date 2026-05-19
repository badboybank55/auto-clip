"""
Background music — priority:
  1. local files in input/music/ (ชื่อไฟล์ขึ้นต้นด้วย calm_/upbeat_/inspirational_)
  2. download Kevin MacLeod CC-BY จาก GitHub mirror
  3. procedural ambient synthesis (numpy + pydub — ไม่ต้อง internet)
"""

import hashlib
import requests
from pathlib import Path
from typing import Optional
from loguru import logger


# GitHub raw ลิงก์ที่เสถียรกว่า archive.org
CATALOG: dict = {
    "calm": [],        # → procedural lofi generation
    "upbeat": [],
    "inspirational": [],
}

HEADERS = {"User-Agent": "auto-clip/1.0 (https://github.com)"}


class MusicLibrary:
    def __init__(self, cache_dir: str = "input/music"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, mood: str = "calm", duration_hint: float = 60.0) -> Optional[str]:
        # 1. local file ก่อน
        local = self._find_local(mood)
        if local:
            logger.info(f"Music (local): {local.name}")
            return str(local)

        # 2. download จาก catalog (ถ้ามี)
        for url in CATALOG.get(mood, []):
            cached = self._cache_path(url)
            if cached.exists() and cached.stat().st_size > 10_000:
                logger.info(f"Music (cache): {cached.name}")
                return str(cached)
            result = self._download(url, cached)
            if result:
                return result

        # 3. procedural — ทำงานเสมอ ไม่ต้อง internet
        logger.info("Music: generating ambient music (procedural)…")
        return self._generate_ambient(duration_hint + 10, mood)

    def _find_local(self, mood: str) -> Optional[Path]:
        import random
        # 1. subdirectory input/music/{mood}/ ก่อน
        mood_dir = self.cache_dir / mood
        if mood_dir.is_dir():
            hits = sorted(mood_dir.glob("*.mp3")) + sorted(mood_dir.glob("*.wav"))
            if hits:
                chosen = random.choice(hits)
                logger.info(f"Music pool [{mood}]: {len(hits)} tracks → '{chosen.name}'")
                return chosen
        # 2. file ในโฟลเดอร์หลักที่ขึ้นต้นด้วย mood
        for pattern in (f"{mood}*.mp3", f"{mood}*.wav"):
            hits = sorted(self.cache_dir.glob(pattern))
            if hits:
                chosen = random.choice(hits)
                if len(hits) > 1:
                    logger.info(f"Music pool: {len(hits)} tracks → '{chosen.name}'")
                return chosen
        return None   # ไม่มีไฟล์ mood นี้ → procedural generation

    def _cache_path(self, url: str) -> Path:
        key = hashlib.md5(url.encode()).hexdigest()[:10]
        return self.cache_dir / f"dl_{key}.mp3"

    def _download(self, url: str, output: Path) -> Optional[str]:
        try:
            resp = requests.get(url, stream=True, timeout=20, headers=HEADERS)
            resp.raise_for_status()
            with open(output, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            if output.stat().st_size < 10_000:
                output.unlink()
                return None
            logger.info(f"Music downloaded: {output.name} ({output.stat().st_size//1024} KB)")
            return str(output)
        except Exception as e:
            logger.debug(f"Music DL failed: {e}")
            if output.exists():
                output.unlink()
            return None

    def _generate_ambient(self, duration_sec: float, mood: str = "calm") -> Optional[str]:
        """สร้างเพลง lofi-style: chord + melody + kick/hihat rhythm"""
        try:
            import numpy as np
            from pydub import AudioSegment

            sr = 44100
            dur = float(duration_sec)
            n = int(sr * dur)
            t = np.linspace(0, dur, n, endpoint=False)

            def sine(freq, amp=1.0, phase=0.0):
                return amp * np.sin(2 * np.pi * freq * t + phase)

            def env_note(start, length, attack=0.02, release=0.08):
                """envelope สำหรับ note — safe boundary check"""
                e = np.zeros(n)
                s = int(start * sr)
                if s >= n:
                    return e
                l = min(int(length * sr), n - s)
                if l <= 0:
                    return e
                a = min(int(attack * sr), l)
                r = min(int(release * sr), max(0, l - a))
                m = max(0, l - a - r)
                if a > 0:
                    e[s:s+a] = np.linspace(0, 1, a)
                if m > 0:
                    e[s+a:s+a+m] = 1.0
                if r > 0:
                    e[s+a+m:s+a+m+r] = np.linspace(1, 0, r)
                return e

            bpm = 85 if mood == "upbeat" else (80 if mood == "inspirational" else 75)
            beat = 60.0 / bpm      # วินาทีต่อ beat
            bar = beat * 4

            # ── chord progression (lofi) ──────────────────────────────────────
            if mood in ("upbeat", "inspirational"):
                # C major: Cmaj7 - Am7 - Fmaj7 - G7
                chords = [
                    [(261.63, 0.18), (329.63, 0.14), (392.00, 0.12), (493.88, 0.10)],
                    [(220.00, 0.18), (261.63, 0.14), (329.63, 0.12), (440.00, 0.10)],
                    [(174.61, 0.18), (220.00, 0.14), (261.63, 0.12), (329.63, 0.10)],
                    [(196.00, 0.18), (246.94, 0.14), (293.66, 0.12), (392.00, 0.10)],
                ]
                bass_notes = [130.81, 110.00, 87.31, 98.00]
            else:
                # A minor lofi: Am7 - Fmaj7 - C - G
                chords = [
                    [(220.00, 0.16), (261.63, 0.13), (329.63, 0.11), (392.00, 0.09)],
                    [(174.61, 0.16), (220.00, 0.13), (261.63, 0.11), (329.63, 0.09)],
                    [(261.63, 0.16), (329.63, 0.13), (392.00, 0.11), (493.88, 0.09)],
                    [(196.00, 0.16), (246.94, 0.13), (293.66, 0.11), (392.00, 0.09)],
                ]
                bass_notes = [110.00, 87.31, 130.81, 98.00]

            sig = np.zeros(n)

            # วน chord progression ตลอดความยาวเพลง
            bars_total = int(dur / bar) + 1
            for b in range(bars_total):
                chord_i = b % len(chords)
                t_start = b * bar
                if t_start >= dur:
                    break
                chord_len = min(bar * 0.95, dur - t_start)
                e = env_note(t_start, chord_len, attack=0.04, release=0.15)
                for freq, amp in chords[chord_i]:
                    sig += amp * sine(freq) * e
                    sig += amp * 0.3 * sine(freq * 2) * e  # octave harmonic
                # bass note (ตีที่ beat 1 และ 3)
                bf = bass_notes[chord_i]
                for beat_off in [0, beat * 2]:
                    be = env_note(t_start + beat_off, beat * 0.7, attack=0.01, release=0.2)
                    sig += 0.22 * sine(bf) * be
                    sig += 0.10 * sine(bf * 2) * be

            # ── melody (pentatonic, short notes) ─────────────────────────────
            if mood in ("upbeat", "inspirational"):
                mel_notes = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25]
            else:
                mel_notes = [220.00, 246.94, 261.63, 293.66, 329.63, 392.00]

            rng = np.random.default_rng(42)
            mel_beat = beat * 0.5
            num_mel = int(dur / mel_beat)
            for i in range(num_mel):
                if rng.random() > 0.45:
                    continue
                freq = rng.choice(mel_notes)
                amp = rng.uniform(0.06, 0.11)
                me = env_note(i * mel_beat, mel_beat * 0.8, attack=0.01, release=0.05)
                sig += amp * sine(freq) * me

            # ── kick drum (sine burst ที่ beat 1 & 3) ────────────────────────
            kick_freq, kick_decay = 80.0, 0.08
            bars_k = int(dur / bar) + 1
            for b in range(bars_k):
                for off in [0, beat * 2]:
                    ts = b * bar + off
                    if ts >= dur:
                        continue
                    ke = env_note(ts, kick_decay, attack=0.002, release=kick_decay * 0.8)
                    kf = np.linspace(kick_freq * 3, kick_freq, int(kick_decay * sr))
                    kbuf = np.zeros(n)
                    s = int(ts * sr)
                    l = min(len(kf), n - s)
                    kbuf[s:s+l] = np.sin(2 * np.pi * kf[:l] * np.linspace(0, kick_decay, l))
                    sig += 0.18 * kbuf * ke

            # ── hi-hat (noise burst ทุก 8th note) ────────────────────────────
            eighth = beat * 0.5
            num_hh = int(dur / eighth)
            for i in range(num_hh):
                ts = i * eighth
                if ts >= dur:
                    continue
                hh_dur = 0.03
                he = env_note(ts, hh_dur, attack=0.001, release=hh_dur * 0.9)
                noise = rng.standard_normal(n) * 0.04
                sig += noise * he

            # ── normalize & master ────────────────────────────────────────────
            peak = max(abs(sig).max(), 1e-9)
            sig = (sig / peak * 0.55 * 32767).astype(np.int16)

            shift = int(sr * 0.004)
            r_ch = np.roll(sig, shift)
            stereo = np.column_stack([sig, r_ch]).flatten().astype(np.int16)

            audio = AudioSegment(stereo.tobytes(), frame_rate=sr,
                                 sample_width=2, channels=2)
            audio = audio.fade_in(3000).fade_out(3000)

            out = self.cache_dir / f"{mood}_beat.mp3"
            audio.export(str(out), format="mp3", bitrate="128k")
            logger.success(f"Beat generated: {out.name} ({dur:.0f}s, {bpm}bpm)")
            return str(out)

        except Exception as e:
            logger.warning(f"Beat generation failed: {e}")
            return None
