{ pkgs ? import <nixpkgs> {} }:

let
  pythonEnv = pkgs.python3.withPackages (ps: with ps; [
    pyside6
    requests
    mutagen
    yt-dlp
  ]);
in
pkgs.stdenv.mkDerivation {
  pname = "music-downloader";
  version = pkgs.lib.fileContents ./VERSION;

  src = ./.;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
    mkdir -p $out/bin $out/share/music-downloader
    cp -r src/* $out/share/music-downloader/

    makeWrapper ${pythonEnv}/bin/python $out/bin/music-downloader \
      --add-flags "$out/share/music-downloader/main.py" \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.ffmpeg pkgs.mpv pkgs.chromaprint pkgs.yt-dlp ]}
  '';
}