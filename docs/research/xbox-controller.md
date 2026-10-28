# Reading an Xbox controller on Windows: per-stack options

Research for Xbox controller support. Researched 2026-10-23.

**Question:** On Windows, how would each candidate stack (Python + PySide6/Qt, Tauri, C# WPF/WinUI 3, Electron) read Xbox controller button presses (USB or Bluetooth) while the app window is focused? Which APIs and libraries, polling or events, hot-plug support, and rough integration effort?

**Short answer:** Every stack can do it, and in every one the Windows OS APIs underneath are **poll-based for button state**. "Events" only appear when a library diffs readings for you. Hot-plug is supported everywhere. Focus-only input, which is what PhotoSort wants, is the **default** behavior of the modern Windows APIs, so nothing extra is needed for it. Effort runs from small (C#, Electron) to small or medium (Python, Tauri). The main difference between stacks is how much glue code each one needs, not whether it can be done at all.

---

## 1. The Windows-level APIs (shared by every stack)

### XInput (`xinput1_4.dll`, ships with Windows 8+)
- **Polling.** `XInputGetState(i, &state)` returns a snapshot. The app compares it with the previous one to detect presses. `dwPacketNumber` changes only when the state changes. ([Getting Started With XInput](https://learn.microsoft.com/en-us/windows/win32/xinput/getting-started-with-xinput))
- **Hot-plug:** there is no event. The return value of `XInputGetState` shows whether a controller is connected in each of 4 slots. Microsoft advises checking empty slots "every few seconds" rather than every frame. (same source)
- **Max 4 controllers.** Supports XUSB/Xbox-compatible pads only.
- **Focus:** `XInputEnable` used to be the way to mute input on focus loss. On **Windows 10+ it is deprecated "as game controller input is automatically enabled/disabled by the system based on the application window focus"**. ([XInputEnable](https://learn.microsoft.com/en-us/windows/win32/api/xinput/nf-xinput-xinputenable)) A focused window therefore gets input with no extra work.
- Plain C ABI, so any language with an FFI can call it in a few lines (Python `ctypes`, C# P/Invoke, Rust).

### Windows.Gaming.Input (WGI, WinRT, Windows 10+)
- **Polling for state:** `Gamepad.GetCurrentReading()` returns a snapshot. Microsoft's guidance is to keep the previous reading and compute "just pressed / just released" yourself. ([Gamepad class](https://learn.microsoft.com/en-us/uwp/api/windows.gaming.input.gamepad), [Input practices for games](https://learn.microsoft.com/en-us/windows/uwp/gaming/input-practices-for-games))
- **Events for hot-plug:** `GamepadAdded` / `GamepadRemoved`. They are raised asynchronously, so the controller list needs a lock. The `Gamepads` list "takes a second or two to populate" at startup. (same sources)
- Supports "any GIP or XUSB compatible gamepad" (covers Xbox One/Series pads over USB and Bluetooth). Also gives battery info and button labels.
- Works in desktop (non-UWP) apps. WinUI 3 docs list it as a key API ([Gamepad and remote interactions](https://learn.microsoft.com/en-us/windows/apps/develop/input/gamepad-and-remote-interactions)). WPF and Win32 .NET apps reach it via a Windows-specific TFM such as `net8.0-windows10.0.19041.0` ([Call WinRT APIs in desktop apps](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/winrt-apis-desktop-apps)).
- **Focus:** WGI only delivers input to a process with a focused window. The `gilrs` docs warn that WGI "needs an in-focus window to receive events" ([gilrs docs](https://docs.rs/gilrs/latest/gilrs/)). That suits PhotoSort.

### GameInput (Microsoft's newest API)
- Microsoft calls it "a functional superset" of XInput, DirectInput, Raw Input, HID and WinRT. It supports **polling or callbacks** and is distributed for PC via the [`Microsoft.GameInput`](https://www.nuget.org/packages/Microsoft.GameInput) NuGet package, back to Windows 10 19H1. Microsoft says to "use the GameInput API for all new code". ([GameInput introduction](https://learn.microsoft.com/en-us/gaming/gdk/docs/features/common/input/overviews/input-overview))
- It is a C/C++ COM-style API. No candidate stack has a first-class binding for it today, so it is overkill for five buttons. Worth knowing about, and Chromium already uses it on Windows 11 behind a feature flag (see section 5).

### SDL (2/3)
- A cross-platform layer over XInput/WGI/HID with a big controller-mapping database. Delivers **events** (device added/removed, button down/up) through SDL's event queue, which you must pump. Its docs say apps "should always support gamepad hotplugging". ([SDL3 Gamepad](https://wiki.libsdl.org/SDL3/CategoryGamepad))
- **Focus caveat:** `SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS` defaults to `"0"`, which disables joystick events while the app is "in the background" ([hint docs](https://wiki.libsdl.org/SDL3/SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS)). When SDL is embedded in a non-SDL GUI (Qt, Tauri), SDL owns no focused window and may treat the app as backgrounded. *Inference, not verified:* you would likely need to set the hint to `1` and gate on your own window focus.

### Browser Gamepad API (Chromium: Electron, WebView2/Tauri)
- **Polling only for buttons.** The spec defines only `gamepadconnected` / `gamepaddisconnected` events. Button and axis change events are left for "more discussion", and the spec recommends polling `navigator.getGamepads()` in step with `requestAnimationFrame`. ([W3C Gamepad spec](https://w3c.github.io/gamepad/), [MDN: Using the Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API/Using_the_Gamepad_API))
- **Gesture gate:** gamepads are not exposed until the user presses a button or moves an axis while the page has focus. A pad already plugged in at launch shows up only after its first press. (MDN, spec)
- Xbox pads get `mapping === "standard"`, so button indices are fixed (0 = A, 1 = B, 12–15 = D-pad, and so on).
- **Chromium's Windows backend:** `AddGamepadPlatformDataFetchers` registers `GameInputDataFetcher` (Windows 11 plus a feature flag) or `WgiDataFetcherWin` otherwise, plus Raw Input and Nintendo fetchers. ([chromium `gamepad_platform_data_fetcher.h`](https://github.com/chromium/chromium/blob/main/device/gamepad/gamepad_platform_data_fetcher.h)) So it runs on WGI under the hood, with WGI's focus behavior.

---

## 2. Python + PySide6 / Qt

- **No Qt-native option.** Qt Gamepad (`QGamepad`) was a Qt 5 module and **was not ported to Qt 6**, so PySide6 has nothing equivalent. A May 2025 qt-development thread discussed reviving it. One maintainer mentioned a revived version targeting Qt 6.10 dev "not part of Qt 6", and others point to a community C++ port, "QtGamepadLegacy". ([qt-development, May 2025](https://lists.qt-project.org/pipermail/development/2025-May/046341.html), [follow-up](https://lists.qt-project.org/pipermail/development/2025-May/046343.html)) I found no PySide6 binding for either. Treat this route as unavailable.
- **Option A: XInput via `ctypes` plus a `QTimer` (recommended shape).** Load `xinput1_4.dll` and call `XInputGetState` every ~16 ms from a `QTimer` on the GUI thread. Diff `wButtons` against the previous state and emit Qt signals or synthesize actions. Rescan empty slots every few seconds for hot-plug. No dependencies, about 60–100 lines. Windows already mutes input when unfocused (see the XInput section), and the app can also check `QGuiApplication.applicationState()`.
- **Option B: [`XInput-Python`](https://pypi.org/project/XInput-Python/).** A wrapper with `get_state`, `get_connected`, and an event generator `get_events()` that yields `BUTTON_PRESSED/RELEASED` and `CONNECTED/DISCONNECTED`. It also offers a background `GamepadThread` (handlers run off the GUI thread, so results must be marshalled back to Qt with signals). Latest release is **0.4.0 from Nov 2019**, zlib license. Small and works, but unmaintained.
- **Option C: SDL through [`pygame`](https://www.pygame.org/docs/ref/joystick.html) or PySDL2.** Gives real `JOYDEVICEADDED/REMOVED` and `JOYBUTTONDOWN` events and a broad device database, but the SDL event queue "needs to be pumped frequently" (do it from a `QTimer`). The background-events hint caveat from the SDL section applies, since the focused window is Qt's, not SDL's. It adds a heavy dependency for what XInput gives directly.
- **Option D: WGI from Python.** Possible through community WinRT projections (pywinrt). Not researched in depth. It adds threading complexity (async events) for little gain over XInput here.
- **Polling or events:** polling under the hood in every case. Libraries B and C synthesize events.
- **Effort:** small for A (one timer class). Packaging stays simple because `xinput1_4.dll` is part of Windows.

## 3. Tauri (Rust core + WebView2 front end on Windows)

Two routes.

- **Front end: browser Gamepad API inside WebView2.** WebView2 is Chromium-based, so `navigator.getGamepads()` should behave as in Edge/Chrome (WGI-backed, polling via `requestAnimationFrame`, gesture gate). **Not confirmed by Microsoft docs:** I found no WebView2 documentation on gamepad support, plus some third-party reports of gamepads not working in WebView2 hosts (e.g. [construct.net comment](https://www.construct.net/en/comments/79672), [pxt-arcade #6176](https://github.com/microsoft/pxt-arcade/issues/6176), the latter on Xbox). Verify with a five-minute spike before relying on it.
- **Rust core: [`gilrs`](https://docs.rs/gilrs/latest/gilrs/) (v0.11.2).** Drain events with `gilrs.next_event()` in a loop or thread, and handle hot-plug through connect/disconnect events (reconnected pads keep their ID). On Windows the **default backend is WGI** (`wgi` feature), with an `xinput` feature as the alternative. Its docs note WGI needs an in-focus window, which is fine here. Forward actions to the front end with Tauri events. Note that the plugin README below says gilrs uses XInput on Windows. The docs.rs page for the current version says WGI is the default.
- **Plugin: [`tauri-plugin-gamepad`](https://github.com/eugenehp/tauri-plugin-gamepad)** (npm `tauri-plugin-gamepad-api`). A gilrs-backed polyfill of the Web Gamepad API, written mainly because WebKit (macOS/Linux) lacks pad support. Latest is 0.0.6 for Tauri 2.x, a small single-maintainer project. Its README warns some devices fire duplicate `gamepadconnected` (native plus polyfill). Lower value on Windows, where WebView2 already has native support.
- **Polling or events:** the front-end route is polling. gilrs presents an event queue that you poll.
- **Effort:** small if WebView2's native API works (pure JS, about 50 lines). Small to medium for gilrs: a Rust thread plus an event bridge, mapping in Rust or JS.

## 4. C# WPF / WinUI 3

- **WGI directly (first-party, recommended shape).** WinUI 3 docs list `Windows.Gaming.Input` as a key gamepad API ([Gamepad and remote interactions](https://learn.microsoft.com/en-us/windows/apps/develop/input/gamepad-and-remote-interactions)). WPF gets the same types by switching to a Windows TFM such as `net8.0-windows10.0.19041.0`, with no NuGet package needed ([Call WinRT APIs in desktop apps](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/winrt-apis-desktop-apps)). Pattern: subscribe to `GamepadAdded/Removed` for hot-plug, poll `GetCurrentReading()` from a `DispatcherTimer` (or `CompositionTarget.Rendering`), and diff `Buttons` flags for press and release ([Input practices for games](https://learn.microsoft.com/en-us/windows/uwp/gaming/input-practices-for-games)). The added and removed events arrive on background threads, so lock the list or marshal to the dispatcher.
- **XInput alternative:** P/Invoke `xinput1_4.dll` yourself (about 20 lines), or use [`Vortice.XInput`](https://www.nuget.org/packages/Vortice.XInput) (v3.8.3, Mar 2026, net8+). Same polling model as section 1.
- **WinUI 3 bonus: built-in XY focus navigation.** XAML has XY focus navigation built in. The D-pad and left stick move focus, A acts as select, and B acts as back, with `XYFocusKeyboardNavigation`, focus engagement and `RequiresPointer` mouse mode documented for Windows App SDK apps (same page). This helps with dialogs and menus. Culling actions (pick/reject/zoom) still need explicit WGI handling. WPF has no gamepad awareness at all.
- **Polling or events:** events for hot-plug, polling for buttons.
- **Effort:** small. All first-party with good docs, roughly 80–120 lines for a `GamepadService` that raises C# events.

## 5. Electron (Chromium renderer)

- **Browser Gamepad API in the renderer** behaves exactly as in section 1: poll `navigator.getGamepads()` in a `requestAnimationFrame` loop, listen to `gamepadconnected/disconnected` for hot-plug, and expect a button press before a pad appears. Chromium's Windows backend is WGI, or GameInput on Windows 11 with a feature flag ([chromium source](https://github.com/chromium/chromium/blob/main/device/gamepad/gamepad_platform_data_fetcher.h)). Since this is the bundled Chromium, behavior is consistent and well-trodden.
- **Native alternatives** (Node addons wrapping XInput/SDL) exist, but they add native build complexity for no gain here.
- **Polling or events:** polling for buttons, events for connect and disconnect.
- **Effort:** small. Pure JS, about 50 lines, no native code.

---

## 6. Comparison

| | Python + PySide6 | Tauri | C# WPF / WinUI 3 | Electron |
|---|---|---|---|---|
| **Native Qt/framework support** | None (Qt Gamepad not in Qt 6) | None in Tauri core | WinUI 3: XY focus nav built in. WPF: none | Chromium Gamepad API built in |
| **Recommended API path** | XInput via `ctypes` + `QTimer` | WebView2 Gamepad API, or `gilrs` in Rust | Windows.Gaming.Input (first-party) | Web Gamepad API |
| **Underlying Windows API** | XInput (or SDL / WGI) | WGI (Chromium or gilrs default), XInput optional | WGI (or XInput) | WGI (GameInput on Win11 behind flag) |
| **Button input model** | Poll + diff (libs can synthesize events) | Poll via `requestAnimationFrame` (JS) / poll event queue (gilrs) | Poll + diff | Poll via `requestAnimationFrame` |
| **Hot-plug** | Rescan slots every few seconds (XInput); events with SDL/XInput-Python | `gamepadconnected` (JS) / gilrs connect events | `GamepadAdded/Removed` events | `gamepadconnected/disconnected` |
| **Focus-only behavior** | Automatic on Win10+ (XInput). SDL needs hint care | Automatic (WGI) | Automatic (WGI) | Automatic, plus gesture gate |
| **Extra dependencies** | None (DLL ships with Windows) | None (JS) / `gilrs` crate | None (TFM change) | None |
| **Maturity / risk** | Low risk with ctypes. XInput-Python unmaintained since 2019 | WebView2 gamepad support undocumented, spike needed. Plugin is tiny | Lowest: first-party, documented | Low: standard Chromium |
| **Rough effort** | Small | Small (JS) to small–medium (Rust bridge) | Small | Small |

Caveats on the table: "Small" means roughly one class or module of under ~150 lines plus a mapping table. No stack has been prototyped. The Tauri/WebView2 row and the SDL-in-Qt focus behavior are the two claims most worth a quick spike.
