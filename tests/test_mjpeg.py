from imirror.mjpeg import iter_jpeg_frames

A = b"\xff\xd8AAAA\xff\xd9"
B = b"\xff\xd8B\xffB\xff\xd9"


def test_frames_split_across_chunks():
    stream = b"--b\r\nContent-Type: image/jpeg\r\n\r\n" + A + b"\r\n--b\r\n\r\n" + B + b"\r\n"
    for size in (1, 2, 3, 7, len(stream)):
        chunks = [stream[i : i + size] for i in range(0, len(stream), size)]
        assert list(iter_jpeg_frames(chunks)) == [A, B]


def test_garbage_only():
    assert list(iter_jpeg_frames([b"hello", b"world\xff"])) == []
