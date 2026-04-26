"""El Consejo — full stack (Phases 2-5 infrastructure).

Resources:
  - S3 buckets: assets, audio-in, audio-out, transcripts, frontend
  - DynamoDB single table
  - SQS queues: conductor + eval (each with DLQ)
  - Lambda: ingest (S3 trigger), conductor (SQS), api (HTTP API), ws (WebSocket),
           eval_worker (SQS)
  - API Gateway HTTP API + WebSocket API
  - CloudFront distribution fronting the frontend bucket
  - IAM permissions scoped tight (bedrock/transcribe/polly use *; AWS requires it).
"""
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_integrations as integrations,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as ddb,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as event_sources,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct

BUILD_DIR = Path(__file__).resolve().parents[1] / "build"


class ElConsejoStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Storage -----------------------------------------------------
        assets_bucket = s3.Bucket(
            self, "AssetsBucket",
            bucket_name=f"elconsejo-assets-{self.account}",
            removal_policy=RemovalPolicy.RETAIN,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )
        audio_in = s3.Bucket(
            self, "AudioInBucket",
            bucket_name=f"elconsejo-audio-in-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.PUT, s3.HttpMethods.POST, s3.HttpMethods.GET],
                allowed_origins=["*"],
                allowed_headers=["*"],
                max_age=3000,
            )],
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(7))],
        )
        audio_out = s3.Bucket(
            self, "AudioOutBucket",
            bucket_name=f"elconsejo-audio-out-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            cors=[s3.CorsRule(
                allowed_methods=[s3.HttpMethods.GET],
                allowed_origins=["*"],
                allowed_headers=["*"],
                max_age=3000,
            )],
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )
        transcripts_bucket = s3.Bucket(
            self, "TranscriptsBucket",
            bucket_name=f"elconsejo-transcripts-{self.account}",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(7))],
        )
        frontend_bucket = s3.Bucket(
            self, "FrontendBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        table = ddb.Table(
            self, "Table",
            table_name="elconsejo",
            partition_key=ddb.Attribute(name="pk", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="sk", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Queues ------------------------------------------------------
        conductor_dlq = sqs.Queue(self, "ConductorDLQ", retention_period=Duration.days(14))
        conductor_queue = sqs.Queue(
            self, "ConductorQueue",
            queue_name="elconsejo-conductor",
            visibility_timeout=Duration.minutes(15),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=2, queue=conductor_dlq),
        )
        eval_dlq = sqs.Queue(self, "EvalDLQ", retention_period=Duration.days(14))
        eval_queue = sqs.Queue(
            self, "EvalQueue",
            queue_name="elconsejo-eval",
            visibility_timeout=Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=2, queue=eval_dlq),
        )

        # --- Lambda common env ------------------------------------------
        env = {
            "ELCONSEJO_TABLE": table.table_name,
            "ELCONSEJO_BUCKET_ASSETS": assets_bucket.bucket_name,
            "ELCONSEJO_BUCKET_AUDIO_IN": audio_in.bucket_name,
            "ELCONSEJO_BUCKET_AUDIO_OUT": audio_out.bucket_name,
            "ELCONSEJO_BUCKET_TRANSCRIPTS": transcripts_bucket.bucket_name,
            "ELCONSEJO_SQS_CONDUCTOR_URL": conductor_queue.queue_url,
            "ELCONSEJO_SQS_EVAL_URL": eval_queue.queue_url,
        }

        def py_fn(name: str, handler: str, timeout_min: int = 1, memory: int = 256,
                  concurrency: int | None = None) -> lambda_.Function:
            kwargs = dict(
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=lambda_.Code.from_asset(str(BUILD_DIR / name)),
                timeout=Duration.minutes(timeout_min),
                memory_size=memory,
                environment=env,
            )
            if concurrency is not None:
                kwargs["reserved_concurrent_executions"] = concurrency
            return lambda_.Function(self, f"{name.title().replace('_', '')}Fn", **kwargs)

        # --- Ingest Lambda ----------------------------------------------
        ingest_fn = py_fn("ingest", "backend.ingest.handler.handler")
        table.grant_read_write_data(ingest_fn)
        conductor_queue.grant_send_messages(ingest_fn)
        audio_in.grant_read(ingest_fn)
        audio_in.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(ingest_fn),
            s3.NotificationKeyFilter(prefix="sessions/"),
        )

        # --- Conductor Lambda -------------------------------------------
        conductor_fn = py_fn(
            "conductor", "backend.conductor.lambda_handler.handler",
            timeout_min=10, memory=1024,
        )
        table.grant_read_write_data(conductor_fn)
        audio_in.grant_read(conductor_fn)
        audio_out.grant_put(conductor_fn)
        transcripts_bucket.grant_read_write(conductor_fn)
        eval_queue.grant_send_messages(conductor_fn)
        conductor_fn.add_event_source(
            event_sources.SqsEventSource(conductor_queue, batch_size=1)
        )
        for action in ("bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                        "transcribe:StartTranscriptionJob",
                        "transcribe:GetTranscriptionJob",
                        "polly:SynthesizeSpeech"):
            conductor_fn.add_to_role_policy(iam.PolicyStatement(actions=[action], resources=["*"]))
        conductor_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe",
                     "aws-marketplace:Unsubscribe"],
            resources=["*"],
        ))

        # --- Eval Lambda ------------------------------------------------
        eval_fn = py_fn(
            "eval_worker", "backend.eval_worker.handler.handler",
            timeout_min=5, memory=512,
        )
        table.grant_read_write_data(eval_fn)
        eval_fn.add_event_source(event_sources.SqsEventSource(eval_queue, batch_size=1))
        eval_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream",
                     "aws-marketplace:ViewSubscriptions", "aws-marketplace:Subscribe",
                     "aws-marketplace:Unsubscribe"],
            resources=["*"],
        ))
        eval_fn.add_to_role_policy(iam.PolicyStatement(actions=["cloudwatch:PutMetricData"], resources=["*"]))

        # --- WebSocket API ----------------------------------------------
        ws_fn = py_fn("ws", "backend.ws.handler.handler")
        table.grant_read_write_data(ws_fn)

        ws_api = apigw.WebSocketApi(
            self, "WsApi",
            connect_route_options=apigw.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("WsConnect", ws_fn)),
            disconnect_route_options=apigw.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("WsDisconnect", ws_fn)),
            default_route_options=apigw.WebSocketRouteOptions(
                integration=integrations.WebSocketLambdaIntegration("WsDefault", ws_fn)),
        )
        ws_stage = apigw.WebSocketStage(
            self, "WsStage", web_socket_api=ws_api, stage_name="prod", auto_deploy=True,
        )
        # Conductor needs to push via mgmt API; give it both the endpoint + permission.
        ws_endpoint = f"https://{ws_api.api_id}.execute-api.{self.region}.amazonaws.com/{ws_stage.stage_name}"
        conductor_fn.add_environment("ELCONSEJO_WS_ENDPOINT", ws_endpoint)
        conductor_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["execute-api:ManageConnections"],
            resources=[f"arn:aws:execute-api:{self.region}:{self.account}:{ws_api.api_id}/*"],
        ))

        # --- HTTP API ---------------------------------------------------
        api_fn = py_fn("api", "backend.api.handler.handler", memory=512)
        table.grant_read_write_data(api_fn)
        audio_in.grant_put(api_fn)
        conductor_queue.grant_send_messages(api_fn)

        http_api = apigw.HttpApi(
            self, "HttpApi",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_headers=["*"],
                allow_methods=[apigw.CorsHttpMethod.ANY],
                allow_origins=["*"],
                max_age=Duration.days(1),
            ),
        )
        http_integration = integrations.HttpLambdaIntegration("ApiIntegration", api_fn)
        http_api.add_routes(path="/presign", methods=[apigw.HttpMethod.POST], integration=http_integration)
        http_api.add_routes(path="/sessions", methods=[apigw.HttpMethod.POST], integration=http_integration)
        http_api.add_routes(path="/sessions/{id}", methods=[apigw.HttpMethod.GET], integration=http_integration)
        http_api.add_routes(path="/feedback/{id}", methods=[apigw.HttpMethod.POST], integration=http_integration)

        # --- Frontend CDN -----------------------------------------------
        distribution = cloudfront.Distribution(
            self, "FrontendCdn",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(frontend_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404, response_http_status=200,
                    response_page_path="/index.html",
                ),
            ],
        )

        # --- Outputs -----------------------------------------------------
        cdk.CfnOutput(self, "OutTableName", value=table.table_name)
        cdk.CfnOutput(self, "OutAudioInBucket", value=audio_in.bucket_name)
        cdk.CfnOutput(self, "OutAudioOutBucket", value=audio_out.bucket_name)
        cdk.CfnOutput(self, "OutAssetsBucket", value=assets_bucket.bucket_name)
        cdk.CfnOutput(self, "OutFrontendBucket", value=frontend_bucket.bucket_name)
        cdk.CfnOutput(self, "OutHttpApiUrl", value=http_api.api_endpoint)
        cdk.CfnOutput(self, "OutWsUrl", value=ws_stage.url)
        cdk.CfnOutput(self, "OutCdnUrl", value=f"https://{distribution.distribution_domain_name}")
