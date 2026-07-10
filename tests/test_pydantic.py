import pytest
from assertpy2 import assert_that

from docopt2 import docopt

pydantic = pytest.importorskip("pydantic")


class Conn(pydantic.BaseModel):
    host: str
    port: int
    verbose: bool


def test_real_pydantic_binds_and_coerces():
    result = docopt("Usage: prog <host> <port> [--verbose]", "h 80 --verbose", schema=Conn)
    assert_that(result).is_instance_of(Conn)
    assert_that(result.port).is_equal_to(80)
    assert_that(result.verbose).is_true()


def test_real_pydantic_ignores_unmodeled_usage_keys():
    result = docopt("Usage: prog <host> <port> [--verbose] [--extra]", "h 80 --extra", schema=Conn)
    assert_that(result.port).is_equal_to(80)


def test_real_pydantic_field_with_differing_alias():
    class Aliased(pydantic.BaseModel):
        number: int = pydantic.Field(alias="port")

    result = docopt("Usage: prog <port>", "80", schema=Aliased)
    assert_that(result.number).is_equal_to(80)


def test_real_pydantic_raises_its_own_validation_error():
    with pytest.raises(pydantic.ValidationError):
        docopt("Usage: prog <host> <port>", "h notanumber", schema=Conn)
