"""Subscribe to data from Adamo."""

import adamo

session = adamo.connect(api_key="ak_your_key_here")

# Blocking iterator — receives samples as they arrive
with session.subscribe("my-robot/sensors/**") as sub:
    for sample in sub:
        print(f"{sample.key}: {sample.payload}")
