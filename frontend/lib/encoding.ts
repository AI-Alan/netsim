/**
 * Line-code preview for the waveform canvas.
 *
 * Rules match backend/layers/physical/encoding.py (NRZ-L, NRZ-I, Manchester IEEE 802.3,
 * Differential Manchester, AMI, 4B5B table + NRZ-I on the 5-bit stream). The simulation
 * uses a larger samples_per_bit (e.g. 100); here we use DISPLAY_SPB for a lighter preview
 * only — rules are identical, resolution differs.
 */
export const DISPLAY_SPB = 16;

/** Number of NRZ-I line symbols after 4B5B (5 per padded nibble); null if not 4B5B. */
export function encodedLineBitCount4B5B(bits: number[]): number {
  const pad = [...bits];
  while (pad.length % 4) pad.push(0);
  return (pad.length / 4) * 5;
}

export function encodeSignal(bits: number[], enc: string, spb: number = DISPLAY_SPB): number[] {
  const samples: number[] = [];

  if (enc === "NRZ-L") {
    bits.forEach(b => { for (let i = 0; i < spb; i++) samples.push(b ? 1 : -1); });
  } else if (enc === "NRZ-I") {
    let lvl = 1;
    bits.forEach(b => { if (b) lvl = -lvl; for (let i = 0; i < spb; i++) samples.push(lvl); });
  } else if (enc === "Manchester") {
    bits.forEach(b => {
      const h = spb / 2;
      for (let i = 0; i < h; i++) samples.push(b ? 1 : -1);
      for (let i = 0; i < spb - h; i++) samples.push(b ? -1 : 1);
    });
  } else if (enc === "Differential Manchester") {
    let lvl = 1;
    bits.forEach(b => {
      if (!b) lvl = -lvl;
      const h = spb / 2;
      for (let i = 0; i < h; i++) samples.push(lvl);
      lvl = -lvl;
      for (let i = 0; i < spb - h; i++) samples.push(lvl);
    });
  } else if (enc === "AMI") {
    let mk = 1;
    bits.forEach(b => {
      if (b) { for (let i = 0; i < spb; i++) samples.push(mk); mk = -mk; }
      else   { for (let i = 0; i < spb; i++) samples.push(0); }
    });
  } else if (enc === "4B5B") {
    const tbl: Record<number, number[]> = {
      0:[1,1,1,1,0],1:[0,1,0,0,1],2:[1,0,1,0,0],3:[1,0,1,0,1],
      4:[0,1,0,1,0],5:[0,1,0,1,1],6:[0,1,1,1,0],7:[0,1,1,1,1],
      8:[1,0,0,1,0],9:[1,0,0,1,1],10:[1,0,1,1,0],11:[1,0,1,1,1],
      12:[1,1,0,1,0],13:[1,1,0,1,1],14:[1,1,1,0,0],15:[1,1,1,0,1],
    };
    const padded = [...bits];
    while (padded.length % 4) padded.push(0);
    const enc5b: number[] = [];
    for (let i = 0; i < padded.length; i += 4) {
      const n = (padded[i] << 3) | (padded[i+1] << 2) | (padded[i+2] << 1) | padded[i+3];
      (tbl[n] || [1,1,1,1,0]).forEach(b => enc5b.push(b));
    }
    let lvl = 1;
    enc5b.forEach(b => { if (b) lvl = -lvl; for (let i = 0; i < spb; i++) samples.push(lvl); });
  }
  return samples;
}

export const ENC_COLORS: Record<string, string> = {
  "NRZ-L":                  "#3b82f6",
  "NRZ-I":                  "#a855f7",
  "Manchester":             "#22c55e",
  "Differential Manchester":"#14b8a6",
  "AMI":                    "#f59e0b",
  "4B5B":                   "#ef4444",
};
