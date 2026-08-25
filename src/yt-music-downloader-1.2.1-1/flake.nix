{
  description = "Music Downloader Nix Flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux"; # Gerekiyorsa aarch64-linux vs.
      pkgs = import nixpkgs { inherit system; };

      pythonDeps = ps: with ps; [
        pyside6
        requests
        mutagen
        yt-dlp
      ];

      myPython = pkgs.python3.withPackages pythonDeps;

      # Uygulama Paket Tanımı
      music-downloader = pkgs.stdenv.mkDerivation {
        pname = "music-downloader";
        version = "1.2.0";

        src = ./.;

        nativeBuildInputs = [ pkgs.makeWrapper ];
        buildInputs = [ myPython ];

        installPhase = ''
          mkdir -p $out/bin $out/share/music-downloader
          
          # Kaynak kodları kopyala
          cp -r src/* $out/share/music-downloader/

          # Wrapper (çalıştırıcı) betiğini oluştur
          makeWrapper ${myPython}/bin/python $out/bin/music-downloader \
            --add-flags "$out/share/music-downloader/main.py" \
            --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg pkgs.mpv pkgs.chromaprint pkgs.yt-dlp ]}
        '';
      };

    in {
      packages.${system}.default = music-downloader;

      # Geliştirme ortamı (nix develop)
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          myPython
          pkgs.ffmpeg
          pkgs.mpv
          pkgs.chromaprint
          pkgs.yt-dlp
        ];
      };
    };
}