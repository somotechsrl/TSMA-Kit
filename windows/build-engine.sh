#!/usr/bin/env bash
# Run inside Cygwin x86_64, with the official JACK2 Windows SDK installed.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$PWD"
mkdir -p .cache-build/windows/sources dist/windows/engine
cd .cache-build/windows
curl -fL --retry 3 https://github.com/radarsat1/liblo/releases/download/0.36/liblo-0.36.tar.gz -o sources/liblo-0.36.tar.gz
echo 'c08d14832e8dcf8f06840405824a4f9611a0cb3daed0198946326c740941c8b6  sources/liblo-0.36.tar.gz' | sha256sum -c -
tar xf sources/liblo-0.36.tar.gz
(cd liblo-0.36; ./configure --disable-shared --disable-tools --disable-examples --disable-doc; make -j2; make install)
curl -fL --retry 3 https://github.com/essej/sooperlooper/archive/92515b21cba27b7db29b06d3afc8396c43a031d4.tar.gz -o sources/sooperlooper-1.7.9.tar.gz
echo '9ebab985f34ea12de76bf9e66d769866c97d6db33620698e490ab73679f4722f  sources/sooperlooper-1.7.9.tar.gz' | sha256sum -c -
tar xf sources/sooperlooper-1.7.9.tar.gz
jackdll=$(find /cygdrive/c/Windows /cygdrive/c/Program\ Files /cygdrive/c/Program\ Files\ \(x86\) -name libjack64.dll -print -quit 2>/dev/null || true)
jackheader=$(find /cygdrive/c/Program\ Files /cygdrive/c/Program\ Files\ \(x86\) -path '*/jack/jack.h' -print -quit 2>/dev/null || true)
test -n "$jackdll" && test -n "$jackheader"
cp "$jackdll" /usr/local/lib/libjack64.dll
cp -r "$(dirname "$jackheader")" /usr/local/include/
mkdir -p /usr/local/lib/pkgconfig
cat > /usr/local/lib/pkgconfig/jack.pc <<'EOF'
prefix=/usr/local
Name: jack
Description: Native Windows JACK client library
Version: 1.9.22
Libs: -L${prefix}/lib -ljack64
Cflags: -I${prefix}/include
EOF
export PKG_CONFIG_PATH=/usr/local/lib/pkgconfig
cd sooperlooper-92515b21cba27b7db29b06d3afc8396c43a031d4
./autogen.sh
./configure --without-gui CXXFLAGS='-O2 -std=gnu++11' ac_cv_lib_jack_jack_client_open=yes
make -j2
make install
cp /usr/local/bin/sooperlooper.exe "$root/dist/windows/engine/"
# cygcheck follows the full dependency closure. Do not redistribute Windows DLLs.
cygcheck /usr/local/bin/sooperlooper.exe > "$root/dist/windows/dependencies.txt"
while IFS= read -r dll; do
  dll=$(printf '%s' "$dll" | sed 's/^[[:space:]]*//;s/\r$//')
  case "$dll" in
    *\\cygwin\\bin\\*.dll|*\\cygwin64\\bin\\*.dll) cp "$(cygpath -u "$dll")" "$root/dist/windows/engine/" ;;
  esac
done < "$root/dist/windows/dependencies.txt"
cp /bin/cygwin1.dll "$root/dist/windows/engine/"
cp COPYING "$root/dist/windows/SOOPERLOOPER-COPYING.txt"
cp "$root/windows/build-engine.sh" "$root/.cache-build/windows/sources/"
echo 'Headless SooperLooper engine built.'
