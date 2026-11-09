"""Small randomly initialized model for registered thermal-change segmentation."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

ARCHITECTURE = "TinyThermalUNet_16_32_64_GroupNorm_v1"


def _block(in_channels, out_channels):
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, 3, padding=1, bias=False),
        nn.GroupNorm(4, out_channels), nn.ReLU(inplace=True),
        nn.Conv2d(out_channels, out_channels, 3, padding=1, bias=False),
        nn.GroupNorm(4, out_channels), nn.ReLU(inplace=True),
    )


class TinyThermalUNet(nn.Module):
    """Two downsampling levels; returns Bx2xHxW logits, without sigmoid/softmax."""

    def __init__(self):
        super().__init__()
        self.encoder1 = _block(3, 16)
        self.encoder2 = _block(16, 32)
        self.bottleneck = _block(32, 64)
        self.pool = nn.MaxPool2d(2, ceil_mode=True)
        self.decoder2 = _block(64 + 32, 32)
        self.decoder1 = _block(32 + 16, 16)
        self.head = nn.Conv2d(16, 2, 1)

    def forward(self, inputs):
        if inputs.ndim != 4 or inputs.shape[1] != 3:
            raise ValueError("Expected Bx3xHxW measured thermal channels")
        first = self.encoder1(inputs)
        second = self.encoder2(self.pool(first))
        bottom = self.bottleneck(self.pool(second))
        up2 = F.interpolate(bottom, size=second.shape[-2:], mode="bilinear", align_corners=False)
        decoded2 = self.decoder2(torch.cat((up2, second), dim=1))
        up1 = F.interpolate(decoded2, size=first.shape[-2:], mode="bilinear", align_corners=False)
        return self.head(self.decoder1(torch.cat((up1, first), dim=1)))


def build_model():
    """Construct a new model; no pretrained or legacy three-class weights."""
    return TinyThermalUNet()
