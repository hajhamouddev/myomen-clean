# Read-only dump of the HP BIOS settings exposed over WMI (root\HP\InstrumentedBIOS).
# These are the same objects Linux hp-bioscfg exposes under /sys/class/firmware-attributes.
# Only Get-CimInstance is used: nothing is written. Needs an elevated PowerShell.
#
#   .\read-bios-settings.ps1 [-Out <path>]

param(
    [string]$Out = (Join-Path $PSScriptRoot '..\research\bios-settings.txt')
)

$ns = 'root\HP\InstrumentedBIOS'
$lines = @("# HP BIOS settings, read $(Get-Date -Format s) on $env:COMPUTERNAME", '')

foreach ($cls in 'HPBIOS_BIOSEnumeration', 'HPBIOS_BIOSInteger', 'HPBIOS_BIOSString',
                 'HPBIOS_BIOSOrderedList', 'HPBIOS_BIOSPassword') {
    $lines += "== $cls"
    try {
        foreach ($s in Get-CimInstance -Namespace $ns -ClassName $cls -ErrorAction Stop | Sort-Object Name) {
            switch ($cls) {
                'HPBIOS_BIOSEnumeration' { $v = "$($s.CurrentValue)   [$($s.PossibleValues -join ' | ')]" }
                'HPBIOS_BIOSInteger'     { $v = "$($s.IntegerValue)   [$($s.LowerBound)..$($s.UpperBound)]" }
                'HPBIOS_BIOSOrderedList' { $v = ($s.Elements -join ', ') }
                'HPBIOS_BIOSPassword'    { $v = "IsSet=$($s.IsSet)" }
                default                  { $v = $s.Value }
            }
            $ro = if ($s.IsReadOnly) { ' (read-only)' } else { '' }
            $lines += "  $($s.Name) = $v$ro"
        }
    } catch {
        $lines += "  error: $($_.Exception.Message)"
    }
    $lines += ''
}

$lines | Set-Content -Path $Out -Encoding utf8
"Wrote $Out"
