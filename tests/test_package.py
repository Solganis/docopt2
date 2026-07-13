from assertpy2 import assert_that

import docopt2


def test_version_is_exposed_lazily_as_a_string():
    # __version__ is resolved on access (PEP 562 __getattr__), not imported eagerly, yet still reads.
    assert_that(docopt2.__version__).is_instance_of(str).matches(r"^\d+\.\d+")


def test_lazy_tooling_loads_on_first_access_and_is_callable():
    # generate_stub lives in a submodule kept off the plain `import docopt2` path; access loads it.
    assert_that(callable(docopt2.generate_stub)).is_true()
    assert_that(callable(docopt2.check)).is_true()


def test_unknown_attribute_raises_attribute_error():
    assert_that(lambda: docopt2.this_name_does_not_exist).raises(AttributeError).when_called_with()
