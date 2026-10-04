{
  description = "Music Downloader Nix Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };

      pythonDeps = ps: with ps; [
        pyside6
        requests
        mutagen
        yt-dlp
      ];

      myPython = pkgs.python3.withPackages pythonDeps;

      music-downloader = pkgs.stdenv.mkDerivation {
        pname = "music-downloader";
        version = pkgs.lib.strings.trim (builtins.readFile ../../VERSION);

        src = ../..;

        nativeBuildInputs = [ pkgs.makeWrapper ];
        buildInputs = [ myPython ];

        installPhase = ''
          mkdir -p $out/bin $out/share/music-downloader
          
          cp -r src/* $out/share/music-downloader/

          makeWrapper ${myPython}/bin/python $out/bin/music-downloader \
            --add-flags "$out/share/music-downloader/main.py" \
            --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg pkgs.chromaprint pkgs.yt-dlp ]}
        '';
      };

    in {
      packages.${system}.default = music-downloader;

      # nix develop
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          myPython
          pkgs.ffmpeg
          pkgs.chromaprint
          pkgs.yt-dlp
        ];
      };
    };
}