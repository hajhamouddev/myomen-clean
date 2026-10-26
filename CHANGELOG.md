# Changelog

All notable changes to **MyOmen** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-05

### Added

- **OMEN Command Center High-Fidelity UI:**
  - Modern dark palette (`#0B0C0E` canvas, `#141518` surface cards, subtle `1px solid rgba(255, 255, 255, 0.07)` borders).
  - Responsive two-state `CollapsibleSidebar` (72px collapsed / 230px expanded) with clean Lucide vector icons (`gauge`, `fan`, `sun`, `music`, `settings`).
  - High-performance live `DualSplineTrace` rendering CPU and GPU temperatures using Catmull-Rom cubic Bézier splines with semi-transparent alpha gradient fills.
  - Dedicated Profile & Presets Hub (`ProfileManagerCard`) with custom profile creation, instant switching, and state persistence.

- **Non-Root ACPI Platform Profile Control:**
  - Bidirectional synchronization with Linux ACPI platform profiles (`/sys/firmware/acpi/platform_profile`).
  - Granular control across `quiet`, `balanced`, and `performance` power modes.
  - Udev permissions granting write access to user session (`0664 plugdev`/`users`) without requiring root/sudo at GUI runtime.

- **Intel RAPL Power Limit Management:**
  - Dynamic power package calculation via `/sys/class/powercap/intel-rapl:0/energy_uj` with rollover compensation.
  - Non-root write permissions for Long/Short Term power constraints (`constraint_0_power_limit_uw`, `constraint_1_power_limit_uw`) via udev rules and `systemd-tmpfiles` (`/usr/lib/tmpfiles.d/myomen.conf`).

- **4-Zone RGB Keyboard Engine:**
  - Direct hardware control for Left, Center, Right, and WASD lighting zones via `hp::kbd_zoned_backlight-*`.
  - 10 built-in presets (Ice Cold, Cyberpunk Neon, Omen Crimson, Deep Matrix, Golden Amber, Ghost White, Solar Flare, Ultraviolet, Breathing Wave, Stealth).
  - Active animation throttle capped strictly at 5 FPS to guarantee zero UI stutter and minimal CPU overhead (<1.5%).
  - Automatic timer shutdown when lighting is disabled or the window is hidden.

- **PipeWire DSP Audio Integration:**
  - System-level PipeWire filter-chain configuration for internal laptop speakers.
  - Custom B&O Windows EQ biquad curves matching HP Omen acoustic profiles.
  - Hard peak limiter strictly set at `-1.0 dBFS` (amplitude 0.891) to protect internal laptop speakers against clipping and thermal degradation.

- **Suspend & Resume Hardware State Recovery:**
  - DBus lifecycle monitor listening on `org.freedesktop.login1.Manager.PrepareForSleep`.
  - Automatic hardware re-application with post-resume stabilization delay (1.0s) restoring ACPI platform profiles, WMI fan states, and RGB lighting configurations after sleep/suspend.
  - Socket health check and rebind guaranteeing uninterrupted IPC communication across sleep cycles.

- **Process Hygiene & GNOME System Tray Integration:**
  - Single-instance daemon architecture using UNIX domain sockets (`myomen-<uid>.sock`).
  - Instant interactive handover (`myomen` CLI forwards activation token to active daemon and exits 0).
  - Clean GNOME AppIndicator tray icon adhering strictly to square dimensions (24x24 standard, 48x48 @2x HiDPI).
  - Consolidated system tray applet featuring live temperature tooltip, quick profile selection, and zero broken indicator dots.

- **Automated FHS-Compliant Packaging:**
  - Debian standalone package pipeline (`packaging/build-deb.sh`) targeting Ubuntu 24.04+ (amd64).
  - Automated systemd user unit (`myomen.service`) for seamless background telemetry.
