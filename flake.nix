{
  description = "Python dev environment with uv and direnv";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
      in {
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.uv
          ];

          shellHook = ''
            if [ ! -d ".venv" ]; then
              echo "Creating virtual environment with uv..."
              uv venv .venv
            fi

            source ./.venv/bin/activate

            if [ -f "pyproject.toml" ]; then
              echo "Syncing dependencies with uv..."
              uv sync
            fi

            echo "$(python --version) | $(uv --version)"
          '';
        };
      });
}
