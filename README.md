# Phone to Phone Transfer

A free, open-source desktop program that copies your data from one Android phone to another over USB.
No account, no cloud, no ads: the data goes phone → your computer → phone.

Interface languages: English, Русский, Українська, Español, Português, Deutsch, Français, Türkçe, 中文.

## What it copies

| Item | Notes |
| --- | --- |
| Photos and videos | `DCIM`, `Pictures`, `Movies` |
| Downloads | `Download` |
| Documents, music, recordings | `Documents`, `Music`, `Recordings`, ringtones, ... |
| WhatsApp media | photos, videos and voice messages (not the chat history) |
| Contacts | exported to `contacts.vcf` and opened for import on the new phone |
| Apps | the apps themselves, without their data or sign-ins |

Nothing is deleted on either phone. A copy can be kept on the computer in the `backup` folder.

## How to use

1. On **both** phones enable *Developer options → USB debugging*
   (Settings → About phone → tap *Build number* seven times to show Developer options).
2. Connect both phones by USB and allow the debugging prompt on each screen.
3. Start the program: download `PhoneTransfer.exe` from [Releases](../../releases) (Windows, nothing to install),
   or run `run.bat` / `python phone_transfer.py` (Python 3.9+, no extra packages).
4. Check the *From* / *To* phones, tick what to copy and press **Transfer**.

The program needs Google's `adb`. If it is not on the computer, it offers to download the official
*SDK Platform-Tools* from Google into the program folder.

## Limits

- Android only (no iPhone).
- App data, chat histories, SMS and call logs are not copied: Android does not give them out over USB.
  Use each app's own backup (WhatsApp: *Settings → Chats → Chat backup*).
- The new phone may refuse some apps (Google Play Protect, or an app made for another brand).
  The program lists them and does not switch any security check off; install those from the app store.
- Contacts stored in a Google account are not exported; they appear after you sign in on the new phone.

## Adding a language

Copy `locales/en.json` to `locales/<code>.json` (two-letter language code), translate the values and keep the
`{placeholders}` as they are. `python check_locales.py` checks that nothing is missing. Pull requests are welcome.

## Building a single .exe (optional)

```
pip install pyinstaller
build.bat
```

The result is `dist/PhoneTransfer.exe`.

## License

MIT. `adb` is part of Android SDK Platform-Tools and is distributed by Google under its own terms;
it is not included in this repository.
