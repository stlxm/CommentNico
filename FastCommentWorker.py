"""Packaged console worker: keeps GUI windowless but captures FFmpeg progress."""
import sys
from fast_comment import main
if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
