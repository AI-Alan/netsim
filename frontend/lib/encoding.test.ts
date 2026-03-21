import { describe, it, expect } from "vitest";
import { encodeSignal, DISPLAY_SPB, encodedLineBitCount4B5B } from "./encoding";

describe("encodeSignal", () => {
  const spb = 8;

  it("NRZ-L: 1 holds high, 0 holds low", () => {
    const s = encodeSignal([1, 0, 1], "NRZ-L", spb);
    expect(s.length).toBe(3 * spb);
    expect(s.slice(0, spb).every(v => v === 1)).toBe(true);
    expect(s.slice(spb, 2 * spb).every(v => v === -1)).toBe(true);
    expect(s.slice(2 * spb).every(v => v === 1)).toBe(true);
  });

  it("NRZ-I: toggles on 1, holds on 0 (start +1)", () => {
    const s = encodeSignal([0, 1, 1, 0], "NRZ-I", spb);
    const seg = (i: number) => s.slice(i * spb, (i + 1) * spb);
    expect(seg(0).every(v => v === 1)).toBe(true);
    expect(seg(1).every(v => v === -1)).toBe(true);
    expect(seg(2).every(v => v === 1)).toBe(true);
    expect(seg(3).every(v => v === 1)).toBe(true);
  });

  it("Manchester: 1 is high-then-low per bit", () => {
    const s = encodeSignal([1], "Manchester", spb);
    const h = spb / 2;
    expect(s.slice(0, h).every(v => v === 1)).toBe(true);
    expect(s.slice(h).every(v => v === -1)).toBe(true);
  });

  it("Manchester: 0 is low-then-high per bit", () => {
    const s = encodeSignal([0], "Manchester", spb);
    const h = spb / 2;
    expect(s.slice(0, h).every(v => v === -1)).toBe(true);
    expect(s.slice(h).every(v => v === 1)).toBe(true);
  });

  it("AMI: zeros at 0, ones alternate polarity", () => {
    const s = encodeSignal([1, 0, 1], "AMI", spb);
    expect(s.slice(0, spb).every(v => v === 1)).toBe(true);
    expect(s.slice(spb, 2 * spb).every(v => v === 0)).toBe(true);
    expect(s.slice(2 * spb).every(v => v === -1)).toBe(true);
  });

  it("4B5B: expands to 5 NRZ-I symbols per nibble", () => {
    expect(encodedLineBitCount4B5B([1, 0, 1, 0])).toBe(5);
    expect(encodedLineBitCount4B5B([1, 0])).toBe(5);
    const s = encodeSignal([1, 0, 1, 0], "4B5B", spb);
    expect(s.length).toBe(5 * spb);
  });

  it("default spb is DISPLAY_SPB", () => {
    const s = encodeSignal([1], "NRZ-L");
    expect(s.length).toBe(DISPLAY_SPB);
  });
});
