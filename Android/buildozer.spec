[app]
 title = Terminxractor
 package.name = terminxractor
 package.domain = com.terminxractor
 source.dir = .
 source.include_exts = py,png,jpg,kv,atlas,json
 version = 1.0.0
 requirements = python3,kivy,yt-dlp
 orientation = portrait
 fullscreen = 0
 android.api = 33
 android.minapi = 21
 android.ndk = 25b
 android.accept_sdk_license = True
 android.permissions = INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

[buildozer]
 log_level = 2
 warn_on_root = 0
