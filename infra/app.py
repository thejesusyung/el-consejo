#!/usr/bin/env python3
"""CDK app entrypoint for El Consejo.

Run from `infra/` dir:
    cdk bootstrap
    python3 -m scripts.build_lambdas  (from repo root, before every deploy)
    cdk deploy
"""
import os

import aws_cdk as cdk

from elconsejo_stack import ElConsejoStack


app = cdk.App()
ElConsejoStack(
    app,
    "ElConsejoStack",
    env=cdk.Environment(
        account=os.getenv("CDK_DEFAULT_ACCOUNT"),
        region="us-east-1",
    ),
)
app.synth()
