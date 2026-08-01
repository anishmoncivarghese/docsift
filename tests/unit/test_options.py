from docsift.core.options import ChunkOptions, CleanOptions, ConversionOptions


def test_defaults_match_prd():
    options = ConversionOptions()
    assert options.chunk.max_tokens == 1000
    assert options.chunk.overlap_tokens == 100
    assert options.clean.remove_image_refs is True
    assert options.clean.keep_page_markers is True


def test_options_serialize_deterministically():
    a = ConversionOptions().model_dump_json()
    b = ConversionOptions(
        clean=CleanOptions(), chunk=ChunkOptions(max_tokens=1000, overlap_tokens=100)
    ).model_dump_json()
    assert a == b
