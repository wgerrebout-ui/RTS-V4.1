[app]
title = Mini RTS
package.name = minirts
package.domain = org.minirts
source.dir = .
source.include_exts = py
version = 0.4
requirements = python3==3.13.1,hostpython3==3.13.1,kivy
p4a.branch = develop
orientation = landscape
fullscreen = 1
android.api = 33
android.minapi = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
