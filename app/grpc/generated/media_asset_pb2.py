# -*- coding: utf-8 -*-
# Generated from contracts/media/media_asset.proto. Do not edit manually.
# source: media/media_asset.proto
"""Generated protocol buffer code for MediaAssetService."""

from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x17media/media_asset.proto\x12\x14streambuted.media.v1"+\n'
    b'\x17GetAssetMetadataRequest\x12\x10\n\x08asset_id\x18\x01 \x01(\t'
    b'"\x8e\x01\n\x15AssetMetadataResponse\x12\x10\n\x08asset_id\x18\x01 \x01'
    b"(\t\x12\x12\n\nasset_type\x18\x02 \x01(\t\x12\x15\n\rowner_user_id"
    b"\x18\x03 \x01(\t\x12\x14\n\x0ccontent_type\x18\x04 \x01(\t\x12\x12\n"
    b"\nsize_bytes\x18\x05 \x01(\x03\x12\x0e\n\x06exists\x18\x06 \x01(\x08"
    b"2\x83\x01\n\x11MediaAssetService\x12n\n\x10GetAssetMetadata\x12-."
    b"streambuted.media.v1.GetAssetMetadataRequest\x1a+."
    b"streambuted.media.v1.AssetMetadataResponseb\x06proto3"
)

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(
    DESCRIPTOR,
    "app.grpc.generated.media_asset_pb2",
    globals(),
)
if _descriptor._USE_C_DESCRIPTORS is False:
    DESCRIPTOR._options = None
