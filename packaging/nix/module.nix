flake:
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.quadrahq;
in
{
  options.programs.quadrahq = {
    enable = lib.mkEnableOption "Quadra, the Roblox launcher";
    package = lib.mkOption {
      type = lib.types.package;
      default = flake.packages.x86_64-linux.quadrahq;
      defaultText = lib.literalExpression "quadra.packages.x86_64-linux.quadrahq";
      description = "Quadra package, including its pinned Darling runtime.";
    };
    runtime = lib.mkOption {
      type = lib.types.enum [
        "ciderdarling"
        "regular"
      ];
      default = "ciderdarling";
      description = "Bundled Darling runtime. Each variant keeps its own prefix and sign-in.";
    };
    withStudio = lib.mkEnableOption "Wine for Roblox Studio";
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = pkgs.stdenv.hostPlatform.system == "x86_64-linux";
        message = "Quadra and Darling require x86_64 Linux.";
      }
    ];
    environment.systemPackages = [ (cfg.package.override { inherit (cfg) runtime withStudio; }) ];
    hardware.graphics.enable = true;
  };
}
