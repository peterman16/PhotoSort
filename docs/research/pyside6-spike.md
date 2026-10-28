# PySide6 real-file spike

Answers "does PySide6 cull real R8 JPGs smoothly?". Run 2026-10-23 on the target PC.

- **Hardware:** Intel i5-1035G7 (8 threads), on AC power but running at about 1.2 GHz of its 1.5 GHz base clock during runs. Screen 2256×1504.
- **Software:** PySide6 6.12.0, Pillow 13.0.0, Python 3.13.
- **Files:** 262 real Canon EOS R8 JPGs (6000×4000; median 7.0 MB, max 15.5 MB) from `Pictures\2024\2025_11_12` and `Pictures\2024\2025_05_29`, read-only.
- **Code:** throwaway, in [spikes/pyside6-cull/spike.py](../../spikes/pyside6-cull/spike.py). Raw output is in `run1.txt`–`run3.txt` next to it.

## Results against the pass bar

| Check | Bar | Result | Verdict |
|---|---|---|---|
| Tapping Next at normal culling speed (5/s) | no blank frames | 0 blank frames in every run, every config | **pass** |
| Holding Next (key-repeat, 10–30/s) | no blank frames | 10/s: 0% blank in the first run, 62–80% in later runs. 15/s and 30/s: 45–96% blank | **fail** |
| Peak RAM | < ~1.5 GB | 280–490 MB | **pass** |
| 100% zoom sharp | < ~0.5 s | full decode 348 ms median (402 max); clip-rect 174 ms | **pass** |

## Decode times (12 real files, median / max ms)

| Path | ms |
|---|---|
| Qt `QImageReader` full | 341 / 378 |
| Qt screen-fit (2256×1504) | 187 / 221 |
| Qt 1/4 | 129 / 171 |
| Pillow full | 154 / 194 |
| Pillow draft screen-fit | 119 / 181 |
| Pillow draft 1/4 | 98 / 133 |
| EXIF embedded thumbnail (160×120) | ~3–5 |

Parallel screen-fit decode with Qt, effective ms per image: 1 thread 214, 2 threads 106, 4 threads 58, 6 threads 49.

Real R8 files decode faster than the synthetic test file (341 vs 405 ms with Qt). **Pillow decodes about twice as fast as Qt's reader** at full size.

## What it means

- **Culling the way you actually cull works.** Pressing Next once per photo you look at, PhotoSort never showed a blank frame, memory stayed under 0.5 GB, and 100% zoom was sharp in well under half a second.
- **Holding Next to fly through a shoot outruns the decoder.** Decoding 4–6 photos at once tops out around 17–20 per second in a clean benchmark, and less inside the app loop. Holding the key generates 10–30 presses per second, so many frames come up blank.
- **Switching to C# WPF wouldn't fix this.** It's a codec limit: WIC took ~407 ms per full decode in the earlier research, the same as Qt. The real fix is design. Show the 160×120 embedded EXIF thumbnail (3–5 ms) blown up as a placeholder while the key is held, skip the photos you're flying past, and decode the one you land on. That's how Lightroom and Photo Mechanic behave.
- **Measurement caveat:** the hold-key numbers vary from run to run (10/s went from 0% to 80% blank). Likely causes are the laptop's power or thermal throttling and the test loop itself competing for the Python GIL. The 5/s result and the decode and zoom numbers were stable.

## Inputs for later tickets

- Prefer **Pillow** (libjpeg-turbo with `draft()`) over `QImageReader` for decoding, then hand the pixels to Qt.
- The embedded thumbnail is only 160×120, which is fine as a held-key placeholder but too small for the grid. The grid needs its own disk thumbnail cache (this feeds the image caching and preloading strategy).
