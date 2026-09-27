from core.names import normalize_name


def test_lowercase_accents_and_punctuation():
    assert normalize_name("José Pérez") == "jose perez"
    assert normalize_name("D.J. Moore") == normalize_name("DJ Moore") == "dj moore"
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("Jaxon Smith-Njigba") == "jaxon smithnjigba"


def test_suffixes_removed():
    assert normalize_name("Kenneth Walker III") == "kenneth walker"
    assert normalize_name("Michael Penix Jr.") == "michael penix"
    assert normalize_name("Anthony Richardson Sr.") == "anthony richardson"
    assert normalize_name("Odell Beckham Jr.") == "odell beckham"


def test_suffix_only_stripped_from_the_end():
    assert normalize_name("V Jefferson") == "v jefferson"


def test_spaces_collapsed_and_dst_trailing_space():
    assert normalize_name("Rams  ") == "rams"
    assert normalize_name("  Dak   Prescott ") == "dak prescott"


def test_alias_table():
    assert normalize_name("Kenneth Gainwell") == normalize_name("Kenny Gainwell")


def test_blank():
    assert normalize_name(None) == ""
    assert normalize_name(float("nan")) == ""
