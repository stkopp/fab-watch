param(
    [string]$Python = 'python',
    [string]$OutputDir = (Join-Path $PSScriptRoot 'dist'),
    [string]$BuildDir = (Join-Path $PSScriptRoot '.build')
)
$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$out = [IO.Path]::GetFullPath($OutputDir)
$build = [IO.Path]::GetFullPath($BuildDir)
New-Item -ItemType Directory -Force -Path $out | Out-Null
New-Item -ItemType Directory -Force -Path $build | Out-Null
& $Python "$src\tools\package_notices.py" "$build\licenses"
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
$options = @('--noconfirm','--clean','--onedir','--windowed','--name','FabWatch',
    '--paths',$src,'--distpath',"$build\dist",'--workpath',"$build\obj",'--specpath',$build,
    '--icon',"$src\fab-watch.ico",'--add-data',"$src\fab-watch.png;.",
    '--add-data',"$src\fab-watch.ico;.",
    '--add-data',"$src\fab-watch-unread.ico;.",
    '--add-data',"$build\licenses;licenses",
    '--add-data',"$src\toast.ps1;.","$src\app.py")
& $Python -m PyInstaller @options
if ($LASTEXITCODE -ne 0) { throw 'App build failed.' }
$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$stub = Join-Path $build 'SetupStub.exe'
$references = @('/reference:System.Windows.Forms.dll','/reference:System.IO.Compression.dll',
    '/reference:System.IO.Compression.FileSystem.dll','/reference:Microsoft.CSharp.dll')
& (Join-Path $framework 'csc.exe') /nologo /target:winexe "/out:$stub" "/win32icon:$src\fab-watch.ico" @references "$src\Setup.cs"
if ($LASTEXITCODE -ne 0) { throw 'Setup build failed.' }
$package = Join-Path $out 'FabWatchSetup-1.4.1-x64.exe'
@'
import hashlib
import io
import pathlib
import struct
import sys
import zipfile

stub, app, result = map(pathlib.Path, sys.argv[1:])
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for file in sorted(app.rglob("*")):
        if file.is_file():
            if file.suffix.lower() in {'.sqlite', '.db', '.log', '.json'} or any(
                    name in {'profiles', 'incidents', 'backups', 'test-reviews'} for name in file.relative_to(app).parts):
                raise RuntimeError('User data must never be included in a release: ' + str(file))
            archive.write(file, file.relative_to(app).as_posix())
payload = buffer.getvalue()
result.write_bytes(stub.read_bytes() + payload + struct.pack("<q", len(payload)) +
                   hashlib.sha256(payload).digest() + b"FABWZIP1")
'@ | & $Python - $stub "$build\dist\FabWatch" $package
if ($LASTEXITCODE -ne 0) { throw 'Setup packaging failed.' }
Get-Item -LiteralPath $package | Select-Object FullName,Length
