# Generated from contracts/media/media_asset.proto. Do not edit manually.
"""Generated gRPC bindings for MediaAssetService."""

import grpc

from app.grpc.generated import media_asset_pb2 as media__asset__pb2


class MediaAssetServiceStub:
    """Client stub for MediaAssetService."""

    def __init__(self, channel: grpc.Channel) -> None:
        """Create a MediaAssetService client stub."""
        self.GetAssetMetadata = channel.unary_unary(
            "/streambuted.media.v1.MediaAssetService/GetAssetMetadata",
            request_serializer=media__asset__pb2.GetAssetMetadataRequest.SerializeToString,
            response_deserializer=media__asset__pb2.AssetMetadataResponse.FromString,
        )


class MediaAssetServiceServicer:
    """Server API for MediaAssetService."""

    def GetAssetMetadata(self, request, context):
        """Return metadata for one media asset."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details("Method not implemented.")
        raise NotImplementedError("Method not implemented.")


def add_MediaAssetServiceServicer_to_server(
    servicer: MediaAssetServiceServicer,
    server: grpc.Server,
) -> None:
    """Register a MediaAssetService implementation with a gRPC server."""
    rpc_method_handlers = {
        "GetAssetMetadata": grpc.unary_unary_rpc_method_handler(
            servicer.GetAssetMetadata,
            request_deserializer=media__asset__pb2.GetAssetMetadataRequest.FromString,
            response_serializer=media__asset__pb2.AssetMetadataResponse.SerializeToString,
        ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
        "streambuted.media.v1.MediaAssetService",
        rpc_method_handlers,
    )
    server.add_generic_rpc_handlers((generic_handler,))
