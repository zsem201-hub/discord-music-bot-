{ pkgs }: {
  deps = [
    pkgs.python311Full
    pkgs.ffmpeg-full
    pkgs.libopus
    pkgs.libffi
  ];
}
