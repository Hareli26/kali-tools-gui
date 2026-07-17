"""🍯 Deception layer — honeypots and the observed-attack knowledge base.

`web_pot` and `collector` are deployed to the SACRIFICIAL host and are not
imported by the production app. `attack_kb` runs on production, inside the
sensor, and is the only part of this package the main app depends on.
"""
