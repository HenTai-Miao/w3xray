# CascLib 3.0

This directory records the pinned source and license for the optional Windows
CascLib backend. The application never downloads native code at startup.

Build the DLL on Windows x64 from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_casclib.ps1
```

The script downloads and builds in the system temporary directory, verifies
the immutable source archive SHA256, then writes these local artifacts:

- `bin/win-x64/CascLib.dll`
- `bin/win-x64/CascLib.dll.sha256`

Both generated files are ignored by Git. Windows distribution builds require
them and verify the hash and x64 PE machine type before invoking PyInstaller.
