"""The grounding checks the evaluation relies on. If these were wrong, every score would be."""

from finn import grounding as checks


def test_numbers_glued_to_a_prefix_count_but_period_labels_do_not():
    assert checks.numbers("Q1 FY27 revenue INR1,350 crore, Rs.594 crore, up 3.5%") == [
        "1,350", "594", "3.5",
    ]  # fmt: skip


def test_a_number_is_grounded_when_the_source_has_it_or_rounds_to_it():
    ref = checks.Reference(
        "Revenue grew 39.8% to INR 7,132 million by March 2026, over three years"
    )
    assert ref.has_number("39.8") and ref.has_number("40") and ref.has_number("7,132")
    assert ref.has_number("2026") and ref.has_number("26")  # March 2026 ~ FY26
    assert ref.has_number("3")  # "three years"
    assert not ref.has_number("41")
    assert not checks.Reference("2.4 times").has_number("2")  # small figures are not rounded


def test_a_unit_conversion_is_reported_apart_from_a_match():
    ref = checks.Reference("total income of INR 7,132 million")
    assert ref.converted_numbers("₹713.2 crore") == ["713.2"]
    assert ref.ungrounded_numbers("₹713.2 crore") == []
    assert ref.ungrounded_numbers("₹812 crore") == ["812"]
    assert checks.Reference("4 GW").converted_numbers("40 GW") == []  # a coincidence, not a unit


def test_names_must_come_from_the_source():
    ref = checks.Reference("Mr. Anup Bagchi has assumed charge as MD & CEO")
    assert ref.ungrounded_names("Anup Bagchi takes charge") == []
    assert ref.ungrounded_names("Anup Bagchi, formerly of ICICI Prudential") == ["ICICI Prudential"]


def test_why_it_matters_must_add_something_specific():
    summary = "The board approved a rights issue of up to 1,000 crore at 27 a share."
    assert checks.repeats("Board approved a rights issue of up to 1,000 crore.", summary)
    assert not checks.repeats(
        "Priced 26% below market, so holders who skip it are diluted.", summary
    )
    assert checks.specific("Priced 26% below market.")
    assert not checks.specific("Fund raising can affect the share price.")


def test_a_sum_of_two_given_figures_is_fair_but_an_invented_total_is_not():
    airtel = checks.Reference("penalty of Rs.1,41,000 and a penalty of Rs.2,12,000")
    assert airtel.unchecked_numbers("total penalty of Rs. 3,53,000") == []
    adani = checks.Reference("16,505.00 4,000.00 240.00 954.96 2,000.00 3,000.00")
    assert adani.unchecked_numbers("facilities totalling Rs 25,749.96 crore") == ["25,749.96"]
