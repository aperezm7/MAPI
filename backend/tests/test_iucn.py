from app.services.iucn import _split_binomial


def test_split_binomial_strips_authorship():
    assert _split_binomial("Panthera onca (Linnaeus, 1758)") == ("Panthera", "onca")


def test_split_binomial_rejects_monomial():
    assert _split_binomial("Amphibia") is None
