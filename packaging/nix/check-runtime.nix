{
  buildFHSEnv,
  writeShellScript,
  quadrahq,
}:
buildFHSEnv (
  quadrahq.args
  // {
    executableName = "quadrahq-runtime-check";
    extraInstallCommands = "";
    runScript = writeShellScript "quadrahq-runtime-check" ''
      set -euo pipefail
      test_root=$(mktemp -d /tmp/quadrahq-runtime-check.XXXXXX)
      export XDG_CONFIG_HOME="$test_root/config"
      export XDG_CACHE_HOME="$test_root/cache"
      export XDG_DATA_HOME="$test_root/data"
      export DPREFIX="$test_root/prefix"
      export QUADRA_PID1_DYLIB=${quadrahq.payload}/lib/quadrahq/launchd_pid1.dylib
      export LIBGL_ALWAYS_SOFTWARE=1
      command=(env LD_PRELOAD=${quadrahq.payload}/lib/quadrahq/darling-noroot.so /usr/bin/darling)
      cleanup() {
        status=$?
        timeout 10 "''${command[@]}" shutdown >/dev/null 2>&1 || true
        if [[ $status == 0 ]]; then
          rm -rf -- "$test_root"
        else
          printf 'Runtime check failed; prefix retained at %s\n' "$test_root" >&2
        fi
      }
      trap cleanup EXIT
      ${quadrahq.payload}/bin/quadrahq --hardware-report --help >/dev/null
      timeout 45 "''${command[@]}" shell /bin/echo "Quadra ${quadrahq.runtime} guest shell: PASS"
    '';
  }
)
