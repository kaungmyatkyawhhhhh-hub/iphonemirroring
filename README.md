# iMirror: iPhone mirroring for Windows

iMirror shows your iPhone's screen in a window on your Windows PC, and lets you use it with your mouse and keyboard, much like Apple's *iPhone Mirroring* on macOS.

| | **Full control** (USB or Wi-Fi) | **View only** (AirPlay, wireless) |
|---|---|---|
| See the screen | ✅ | ✅ |
| Click / swipe / long-press / scroll | ✅ | ❌ |
| Type with the PC keyboard, paste with Ctrl+V | ✅ | ❌ |
| Home, app switcher, lock, volume, screenshot | ✅ | ❌ |
| Phone audio on the PC | ❌ | ✅ |
| Setup on the iPhone | WebDriverAgent installed once | none |

> **Why two modes?** Apple's own iPhone Mirroring uses private Continuity protocols that only work between a Mac and an iPhone. On Windows, the only ways to *control* an iPhone go through Apple's UI-testing framework, which is what **WebDriverAgent** (an open-source test server) runs on. The AirPlay mode needs nothing installed on the phone, but iOS doesn't accept input from an AirPlay receiver, so it is view-only.

## Using it

| PC | iPhone |
|---|---|
| Click | Tap |
| Click and hold (½ s) | Long-press |
| Drag | Swipe / drag (your path and speed are replayed) |
| Mouse wheel | Scroll |
| Type | Types into the focused text field (Backspace and Enter work) |
| Ctrl+V | Pastes the PC clipboard as typed text |
| Ctrl+H / Ctrl+Tab / Ctrl+L | Home / App switcher / Lock-unlock |
| Ctrl+Up / Ctrl+Down | Volume |
| Ctrl+S | Save a full-resolution screenshot |
| Ctrl+T | Keep the window on top |

## Install iMirror

1. Install **Python 3.10 or newer** from python.org. Tick "Add Python to PATH".
2. Download this repository and double-click **`run.bat`**. The first run installs PySide6 and requests into a local `.venv`.

To build a standalone `iMirror.exe` instead, run `build_windows.bat`. The output goes to `dist\iMirror\`.

## Set up full-control mode (one time)

### 1. USB drivers
Install **Apple Devices** from the Microsoft Store (or iTunes). It provides the *Apple Mobile Device Service* that Windows needs to talk to an iPhone over USB. Connect the phone and tap **Trust**.

### 2. Put WebDriverAgent on the iPhone
WebDriverAgent ([appium/WebDriverAgent](https://github.com/appium/WebDriverAgent)) is an app that must be signed with your Apple ID.

- **With a Mac (most reliable):** open `WebDriverAgent.xcodeproj` in Xcode, choose your team under *Signing* for the `WebDriverAgentRunner` target, then run it once on the phone with *Product → Test*.
- **Without a Mac:** download `WebDriverAgentRunner-Runner.zip` from the WebDriverAgent releases page. Rename it to `.ipa` and sideload it with a tool such as Sideloadly using your Apple ID. Apps signed with a free Apple ID expire after 7 days and must be sideloaded again.

Then on the iPhone:
- iOS 16 or later: **Settings → Privacy & Security → Developer Mode → On**.
- **Settings → General → VPN & Device Management**: trust your developer certificate.

### 3. Start WebDriverAgent and forward its ports from Windows
Install [go-ios](https://github.com/danielpaulus/go-ios) (`ios.exe`) and put it on your PATH. Then open **iMirror → Settings…** and fill in:

- **USB tunnel command:**
  ```
  ios forward {wda_port} 8100 && ios forward {mjpeg_port} 9100
  ```
- **Launch WDA command** (use the bundle id your WebDriverAgent was installed with; some sideloading tools change it):
  ```
  ios runwda --bundleid=com.facebook.WebDriverAgentRunner.xctrunner --testrunnerbundleid=com.facebook.WebDriverAgentRunner.xctrunner --xctestconfig=WebDriverAgentRunner.xctest
  ```

On **iOS 17 and later**, go-ios also needs a tunnel. Keep `ios tunnel start --userspace` running in a terminal while you use iMirror (see the go-ios README).

Click **Connect**. iMirror starts both commands, waits for WebDriverAgent, and starts streaming. Each helper's output is written to `%APPDATA%\iMirror\logs\`.

**Over Wi-Fi:** once WebDriverAgent is running, it also listens on the phone's Wi-Fi address. Set *WebDriverAgent host* to the phone's IP (Settings → Wi-Fi → ⓘ on the iPhone) and leave both commands empty.

### Tuning
In Settings you can change the frame rate, JPEG quality and stream scale. Lower values reduce lag on slow connections, higher values look sharper. *Shot* always saves at full resolution.

## Set up view-only AirPlay mode

1. Install **Bonjour** for Windows. It comes with iTunes, or you can install Apple's *Bonjour Print Services*.
2. Install [UxPlay](https://github.com/FDH2/UxPlay), an open-source AirPlay mirroring receiver, by following its Windows instructions. iMirror looks for `uxplay.exe` on your PATH, in `C:\msys64\ucrt64\bin`, in `C:\Program Files\UxPlay`, and in a `bin` folder next to iMirror. You can also set the path in Settings.
3. **iMirror → AirPlay receiver.** Allow it through Windows Firewall when asked.
4. On the iPhone: **Control Center → Screen Mirroring → iMirror**. The PC and the phone must be on the same network.

## Trying it without an iPhone

```
python tools/mock_wda.py
```
This runs a fake WebDriverAgent on ports 8100 and 9100. Click **Connect** in iMirror to see a fake phone screen that draws a dot wherever you tap and shows what you type.

## Development

```
pip install -r requirements.txt pytest
pytest
```

| File | What it does |
|---|---|
| `imirror/app.py` | Qt window, phone frame rendering, and input handling |
| `imirror/wda.py` | WebDriverAgent HTTP client (touch actions, buttons, keyboard) |
| `imirror/mjpeg.py` | Reads the MJPEG screen stream |
| `imirror/gestures.py` | Turns mouse input into taps, long-presses, swipes and scrolls |
| `imirror/helpers.py` | Starts and stops go-ios, iproxy and UxPlay |
| `tools/mock_wda.py` | Fake device for testing |

## Limitations

- Notifications, phone calls, and audio in control mode are not mirrored. iOS does not expose them to WebDriverAgent.
- Typing goes to whichever text field is focused on the phone. Some special characters may not type correctly.
- Control mode has a noticeable delay (it streams JPEG frames over HTTP). Lower the stream settings if it feels slow.
- iMirror is not affiliated with Apple. "iPhone" and "AirPlay" are trademarks of Apple Inc.
