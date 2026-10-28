# Stack performance research: culling 5,000 large JPGs on Windows

Researched 2026-10-23 while choosing PhotoSort's tech stack. This note gathers the evidence and gives a recommendation with its tradeoffs.

## TL;DR

- **The JPEG codec doesn't decide this.** Every candidate stack ends up using libjpeg-turbo or Windows' own WIC codec, and on this PC both take about 400 ms to decode one full R8 JPEG. Smooth next/previous navigation comes from **decoding ahead on several threads and keeping a bounded cache of decoded images**, not from picking a faster language.
- **Memory sets the ceiling.** One decoded 6000×4000 frame is about 96 MB as RGBA. Holding the current image ±3 at full resolution costs about 670 MB. Caching screen-sized copies and decoding full resolution only for 100% zoom is far cheaper.
- **Native stacks give you direct control of that cache.** That means Python + PySide6, C# (WPF or WinUI 3), and Qt/C++. Web stacks (Tauri, Electron) hand image decoding and caching to Chromium, which you can steer but not own. That is the main performance risk for an image-heavy app.

## Facts about the workload

| Fact | Value | Source |
|---|---|---|
| R8 JPEG L resolution | 6000×4000 (24 MP) | Canon R8 spec, [shop.in.canon](https://shop.in.canon/eos-r8-body.html) |
| R8 JPEG L/Fine file size | ~8.2 MB (Canon test standard) | same |
| Decoded size, RGBA 8-bit | 6000 × 4000 × 4 B = **96 MB** per image | arithmetic |
| Decoded size, YCbCr 4:2:0 planar | 12 bpp ≈ 36 MB | [WIC JPEG YCbCr support](https://learn.microsoft.com/en-us/windows/win32/wic/jpeg-ycbcr-support) (bits-per-pixel table) |
| Full shoot fully decoded | 5,000 × 96 MB ≈ 480 GB → you can only cache a small window | arithmetic |

## Local measurement (this PC)

These numbers come from the target machine: Intel Core i5-1035G7 (4C/8T laptop part, 2019), Windows 11, Python 3.13, Pillow 11.1.0. `PIL.features.check_feature("libjpeg_turbo")` returns `True`, so the Pillow wheel ships libjpeg-turbo (8.0 API). WPF/WIC was run from Windows PowerShell 5.1.

The test file was synthetic: a 6000×4000 JPEG at quality 92 with 4:2:2 chroma subsampling, 8.65 MB, matching the R8's size. Each figure is the best of 5 runs after a warm-up. The scripts were kept in the session scratchpad and aren't part of the repo. **Caveat:** synthetic noise doesn't compress like a real photo. Re-run on real R8 files before trusting the exact figures.

| Decode path | Full res | 1/2 | 1/4 | 1/8 |
|---|---|---|---|---|
| Pillow (libjpeg-turbo), `Image.draft()` DCT scaling | **405 ms** | 296 ms | 230 ms | 160 ms |
| WPF `BitmapImage` (WIC), `DecodePixelWidth` = 3000/1500/750 | **407 ms** | 386 ms | 334 ms | 301 ms |

| Pillow, parallel full-res decodes (8 images) | Effective ms/image |
|---|---|
| 1 thread | 382 |
| 2 threads | 168 |
| 4 threads | 90 |

What the measurements show:

1. **Decoding on demand is too slow everywhere.** About 400 ms per image is well above the ~100 ms where a keypress stops feeling instant. libjpeg-turbo and WIC perform about the same, and every candidate stack uses one of them: Qt's bundled codec, Pillow, Chromium in WebView2 and Electron, and the Rust `turbojpeg` crate use libjpeg-turbo, while WPF and WinUI use WIC. So **look-ahead decoding is required on every stack**.
2. **Scaling during decode helps less than you'd hope** at 8 MB per file. Huffman (entropy) decoding takes a large share of the time and doesn't shrink when you scale. Even 1/8-scale grid thumbnails cost 160–300 ms each when decoded from the full JPEG. Generating 5,000 thumbnails that way takes **~4 minutes at 4 threads**, so the grid needs embedded previews or a persistent thumbnail cache (see below).
3. **Decoding scales almost linearly with threads**, at least in Python. Pillow releases the GIL while decoding, so a thread pool decoding the next 2–4 images keeps up with fast keypresses: about 90 ms of effective throughput per image at 4 threads.

## Building blocks, by concern

### JPEG decoding and scaling

- **libjpeg-turbo** uses SIMD and decompresses 2.1–3.4× faster than libjpeg v6b, and 1.9–4.3× faster than v8d, on x86-64 ([libjpeg-turbo performance page](https://libjpeg-turbo.org/About/Performance); methodology uses `tjbench` at quality 95 across 4:2:0, 4:2:2 and 4:4:4).
- **Qt (PySide6 / C++)**:
  - Qt bundles libjpeg-turbo in `qtbase/src/3rdparty/libjpeg` ([source](https://github.com/qt/qtbase/tree/dev/src/3rdparty/libjpeg)).
  - Its JPEG plugin supports `ScaledSize`, `ClipRect` and `ImageTransformation`. It maps `setScaledSize` to libjpeg's DCT scaling (`scale_num/scale_denom`) and applies EXIF orientation automatically ([qjpeghandler.cpp](https://github.com/qt/qtbase/blob/dev/src/plugins/imageformats/jpeg/qjpeghandler.cpp)).
  - `QImageReader` is documented as reentrant, so you can use one per worker thread ([QImageReader docs](https://doc.qt.io/qt-6/qimagereader.html)).
  - `ClipRect` matters for 100% zoom: you can decode only the region you're viewing, though libjpeg still has to entropy-decode up to that region.
- **Pillow**: `Image.draft()` requests a reduced-size JPEG decode ([Pillow Image docs](https://pillow.readthedocs.io/en/stable/reference/Image.html)). As measured above, it's libjpeg-turbo and releases the GIL.
- **WIC (C#)**:
  - `BitmapImage.DecodePixelWidth`: "The JPEG and PNG codecs natively decode the image to the specified size" ([docs](https://learn.microsoft.com/en-us/dotnet/api/system.windows.media.imaging.bitmapimage.decodepixelwidth)).
  - Since Windows 8.1, WIC can return native YCbCr planes and hand colour conversion to the GPU through Direct2D, which cuts memory and load time. From Windows 10, `ID2D1ImageSourceFromWic` does this automatically and can cache only the subregions in use, which suits 100% zoom ([WIC JPEG YCbCr support](https://learn.microsoft.com/en-us/windows/win32/wic/jpeg-ycbcr-support)).
  - **This is the only GPU-assisted JPEG path among the candidates.** It needs Direct2D interop, which is plain in C++, workable from C# through Win2D or Vortice, and impractical from Python.
- **Web stacks**:
  - Chromium decodes `<img>` content itself; WebView2 is Chromium-based ([Tauri webview versions](https://v2.tauri.app/reference/webview-versions/)).
  - `HTMLImageElement.decode()` lets you pre-decode an image before it goes in the DOM ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/HTMLImageElement/decode)).
  - Chromium alone decides how long decoded bitmaps stay in memory. In my experience it evicts them under memory pressure, but **this is not confirmed from a primary source**, so a prototype should test it.
  - Doing your own decode in Rust or Node and shipping pixels to the page means moving about 96 MB per frame over IPC. Tauri's raw binary IPC (`tauri::ipc::Response` → `ArrayBuffer`) avoids JSON encoding but not the copy ([Tauri core API](https://v2.tauri.app/reference/javascript/api/namespacecore/)).

### Thumbnails for the grid

- Decoding 5,000 full JPEGs for the grid takes minutes on this PC (see the measurements). Better options, in rough order:
  1. **Windows Shell thumbnail cache**, through `IShellItemImageFactory` or WinRT `StorageFile.GetThumbnailAsync`. It reuses Explorer's cache and is easiest from C#; Rust can reach it through the `windows` crate and Python through ctypes or pywin32.
  2. **Embedded EXIF IFD1 thumbnail**: near-instant to read, but usually tiny (typically 160×120 in Canon JPEGs; **check on a real R8 file**). Fine as a placeholder, soft at grid sizes.
  3. **Your own disk thumbnail cache** (for example 1/8-scale JPEGs in the Shoot folder or `%LOCALAPPDATA%`), built in the background after Import and reused across sessions. This works on any stack.
- Embedded previews in the `.CR3` aren't useful here: you cull JPGs, and the RAWs stay on the Card.

### Preloading, caching and memory

- On every stack the design is the same: a background pool decodes N±k images at screen resolution, an LRU cache has a memory budget, and full-resolution decoding (or a clip-rect decode) happens only when 100% zoom is toggled. Only the control you get differs:
  - **Qt / C# / Rust-native**: you own the bitmaps, the budget and the eviction. Qt `QPixmapCache` / `QImage`, WPF `BitmapSource.Freeze()` to share across threads, WinUI `SoftwareBitmap` / Win2D.
  - **Python**: same control. Pillow and Qt both release the GIL while decoding, so threads are enough; Python's speed isn't the bottleneck because decoding happens in C.
  - **Tauri / Electron**: the cache lives in Chromium's renderer. You can keep `Image` objects or `ImageBitmap`s alive in JS to hold decoded data, but memory accounting is opaque. WebView2 runs its own browser, GPU and renderer processes, adding baseline overhead per app ([WebView2 performance](https://learn.microsoft.com/microsoft-edge/webview2/concepts/performance)). Electron additionally ships its own Chromium and Node.

### File operations

| Need | Python + PySide6 | Tauri (Rust) | C# | Electron |
|---|---|---|---|---|
| Copy RAWs | `shutil.copy2` / `QFile::copy` | `std::fs::copy` | `File.Copy` | `fs.copyFile` |
| Recycle Bin delete | `Send2Trash` 2.1.0 (Jan 2026; IFileOperation with pywin32, else SHFileOperation) ([PyPI](https://pypi.org/project/Send2Trash/)) | `trash` crate 5.x ([docs.rs](https://docs.rs/trash/latest/trash/)) | `FileSystem.DeleteFile(..., RecycleOption.SendToRecycleBin)`, built into .NET ([docs](https://learn.microsoft.com/en-us/dotnet/api/microsoft.visualbasic.fileio.filesystem.deletefile)) | `shell.trashItem(path)` ([docs](https://www.electronjs.org/docs/latest/api/shell)) |
| Removable-drive detection | `QStorageInfo::mountedVolumes()`, but no `isRemovable` and no change signal ([docs](https://doc.qt.io/qt-6/qstorageinfo.html)); use Win32 `GetDriveType` through ctypes and poll, or `WM_DEVICECHANGE` | Win32 through the `windows` crate | `DriveInfo.DriveType == Removable`; `WM_DEVICECHANGE` / WMI events | Node: poll, or a native module |

All four handle file operations easily. C# needs the least extra code because everything is in the standard library.

### EXIF / XMP read and write (picks/rejects that Lightroom can read)

- **Python**: `python-exiv2` 0.20 ships Windows wheels **with libexiv2 bundled** (≥0.28.2), reads and writes EXIF/IPTC/XMP, and has BMFF/CR3 support on by default since 0.17 ([GitHub](https://github.com/jim-easterbrook/python-exiv2)). Writing `.xmp` sidecars by hand (XML) is also simple.
- **Rust**: `xmp_toolkit` 1.12 wraps Adobe's own XMP Toolkit (March 2025 SDK) and needs the MSVC toolchain on Windows, plus a C++ build ([docs.rs](https://docs.rs/xmp_toolkit/latest/xmp_toolkit/)). That's the most authoritative XMP implementation, at the cost of a heavier build.
- **C#**: WIC metadata query writers (`/xmp/...` paths through `BitmapMetadata` / `InPlaceBitmapMetadataWriter`) can write XMP into JPEGs. This is a fiddly API, often paired with an XMP sidecar written as XML. NuGet bindings for exiv2/XMP exist but aren't first-party.
- **Electron (Node)**: `exiftool-vendored` (wraps Phil Harvey's ExifTool; Perl ships inside the package) or sidecar XML.
- Portability: per the map's "prefer portable formats" preference, **XMP sidecars** (`IMG_1234.xmp`) work with any stack and avoid rewriting the JPG. Every stack can write them as plain XML, so this concern doesn't decide the stack.

### Effort for one hobbyist developer

- **Python + PySide6**: reuses the existing scripts (`importjpg.py`, `replaceRawsFromJPG.py`) and the language you already know. Qt has everything needed: image view, `QGraphicsView` zoom/pan, and a model/view grid. The Qt Gamepad module wasn't carried into Qt 6, so controller support would need SDL or XInput through a separate library (see ticket 002). Packaging with PyInstaller or Nuitka produces a large but workable folder or exe.
- **C# WPF**: mature, well documented, built-in Recycle Bin and drive APIs, WIC built in. Visual Studio Community is free. You'd be learning C# and XAML. WinUI 3 is the modern option, but its deployment is fussier: it's framework-dependent by default, can be self-contained/unpackaged, but **can't be a single-file EXE** ([Windows App SDK self-contained deploy](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/self-contained-deploy/deploy-self-contained-apps)).
- **Tauri**: small binaries and a pleasant UI layer, but two languages (Rust + TS/JS) and Rust's learning curve. The image pipeline, the app's hardest part, is the one where you control the least.
- **Electron**: the most familiar UI tooling, but the heaviest runtime, and it has the same Chromium-owned image cache issue as Tauri with no performance advantage.
- **Others considered**:
  - **Qt/C++**: what FastRawViewer and digiKam use. Fastest ceiling, but C++ is too costly for one hobbyist.
  - **Rust native GUI** (egui / Slint): full control of decoding, but young widget ecosystems for grids and zoom views.

Neither is recommended, but they're there if a prototype shows Python falling short.

## Comparison table

Ratings: ++ strong, + good, 0 neutral, − weak, −− poor.

| Criterion | Python + PySide6 | C# WPF | C# WinUI 3 | Tauri | Electron |
|---|---|---|---|---|---|
| JPEG decode speed (codec) | + libjpeg-turbo (Qt / Pillow) | + WIC (≈ same on this PC) | + WIC, + D2D YCbCr path | + Chromium libjpeg-turbo | + Chromium libjpeg-turbo |
| Decode while scaling / clip-rect | ++ ScaledSize + ClipRect | + DecodePixelWidth | + DecodePixelWidth, D2D subregion caching | 0 only if you decode in Rust | 0 |
| GPU assist | 0 (OpenGL texture upload only) | 0 | + Direct2D YCbCr (extra work) | 0 browser's own | 0 browser's own |
| Parallel look-ahead decode | + threads (GIL released) | ++ | ++ | ++ in Rust / − in page | − / worker + native module |
| Control over cache and memory | ++ | ++ | ++ | − Chromium owns decoded images | − same, plus heavier baseline |
| Grid thumbnails | + own cache; Shell API through ctypes | ++ Shell thumbnail API | ++ `GetThumbnailAsync` | + own cache in Rust | + own cache via sharp/native |
| Recycle Bin / copy / drive detection | + (Send2Trash, ctypes) | ++ built in | ++ built in | + crates | + built-in trash, polling for drives |
| EXIF/XMP read/write | ++ python-exiv2 (bundled) | 0 WIC is fiddly | 0 same | + Adobe XMP Toolkit (C++ build) | + exiftool-vendored |
| Packaging | 0 PyInstaller/Nuitka, ~100+ MB | + single-file exe possible | − no single-file exe | ++ small exe (uses OS WebView2) | − ~100+ MB |
| Hobbyist effort (given current Python) | ++ | + | 0 | − two languages, Rust | + if fluent in JS |
| Reuse of existing scripts | ++ | − | − | − | − |

## Recommendation with tradeoffs (input to ticket 003, not a decision)

**Front-runner: Python + PySide6.** Runner-up: **C# WPF**. Ranked below both: **Tauri** and **Electron**.

- **Why Python + PySide6 leads**:
  - Its decode speed is on par with every other option, because the codec is the same (measured).
  - It lets you build the real fix (threaded look-ahead decode, a screen-res LRU cache, clip-rect decode for 100% zoom) with full control.
  - It has the best metadata library of the group (`python-exiv2` with bundled libexiv2) and reuses existing code and skills.
  - **Tradeoffs:** a large distributable; no `isRemovable`, so drive detection needs ctypes; Shell thumbnail access needs ctypes or pywin32; and a GPU-assisted decode path is out of reach if it ever becomes necessary.
- **Why C# WPF is a close second**:
  - The platform-specific needs (Recycle Bin, drive types, Shell thumbnails, WIC) are first-party and built in, and packaging into one exe is easy.
  - Choose it if you'd rather learn C# than live with Python packaging, or if a prototype shows Python UI overhead (not decoding) causes stutter.
  - **Tradeoffs:** you learn a new language and XAML; XMP writing through WIC is clunky; WinUI 3 adds deployment friction for little gain in this app.
- **Why the web stacks rank lower**:
  - Their main advantage, UI ergonomics, doesn't help where it matters most here. Chromium owns the decoded-image cache, and moving pixels from native code costs ~96 MB per frame.
  - Tauri's small footprint is attractive. But two languages, and Rust for the image pipeline, is a big jump for one hobbyist, with no measured speed gain.

**Whatever stack wins**, the cull-feel prototype (ticket 004) should check these before committing:

1. Real R8 JPEGs: decode time (full and 1/4) and EXIF thumbnail size.
2. Holding key-repeat on Next for 5 s with 4-thread look-ahead and a cache of ~12 screen-res frames. Measure dropped frames and peak RAM.
3. Time from 100% zoom toggle to sharp image, with full decode vs clip-rect decode.

## Open questions / not verified

- Pillow's exact bundled libjpeg-turbo version (only "8.0 API" and `libjpeg_turbo=True` are confirmed locally).
- Chromium/WebView2's policy for evicting decoded images; no primary doc found.
- Whether WPF `BitmapImage` actually uses DCT scaling at 1/2 to 1/8. The measured speedup was smaller than Pillow's, so WIC may apply it only partly through this API.
- Free-threaded CPython (3.14t) wasn't evaluated; it isn't needed, since decoding already releases the GIL.
