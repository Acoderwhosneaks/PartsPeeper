"""partspeeper — universal 2D parts-input -> parts.csv pipeline.

Stages (see ../part_contract.md):
    [A extract]  PDF -> Word[]
    [B digest]   Word[] -> RawPart[]
    [C classify] RawPart[] -> PartRecord[]
    [D assemble] PartRecord[] -> parts.csv + validation report   (this module: assemble, validate)
"""
__all__ = ["assemble", "validate"]
