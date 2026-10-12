"""ArmorIQ client construction.

Policy evaluation is not part of this scaffold. ``create_armoriq_client`` uses
the documented ``ArmorIQClient`` constructor and nothing else. It does not
capture plans, mint intent tokens, invoke tools, or return an allow or block
decision.
"""

from armoriq_sdk import ArmorIQClient
from dotenv import load_dotenv


def create_armoriq_client() -> ArmorIQClient:
    """Build a client with the SDK's own API-key resolution.

    ``ArmorIQClient`` checks an explicit constructor argument, then
    ``ARMORIQ_API_KEY``, then ``~/.armoriq/credentials.json``. This helper
    passes no key of its own. A missing key raises the SDK's
    ``ConfigurationException``.
    """
    load_dotenv()
    return ArmorIQClient()
