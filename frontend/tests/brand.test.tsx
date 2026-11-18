import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DevFlowLogo } from "@/components/brand/DevFlowLogo";
import { MARK } from "@/components/brand/geometry";

describe("Logo DevFlow", () => {
  it("renders the full logo with light and dark images under one accessible name", () => {
    const { container } = render(<DevFlowLogo variant="full" size={44} />);
    const logo = screen.getByRole("img", { name: "DevFlow" });
    const images = container.querySelectorAll("img");
    expect(images).toHaveLength(2);
    expect(images[0]!.getAttribute("src")).toMatch(/brand\/devflow-logo\.png$/);
    expect(images[1]!.getAttribute("src")).toMatch(/brand\/devflow-logo-dark\.png$/);
    expect(images[0]).toHaveAttribute("alt", "");
    expect(logo).toHaveStyle({ height: "44px", width: `${Math.round(44 * 1.5531)}px` });
  });

  it("draws the bulb and gear symbol, detailed from 56 px and compact below", () => {
    const { container, rerender } = render(<DevFlowLogo variant="symbol" size={72} />);
    expect(screen.getByRole("img", { name: "DevFlow" })).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute("viewBox", MARK.detailed.viewBox);
    expect(container.querySelector('path[stroke="currentColor"]')).not.toBeNull(); // engrenage : couleur du texte
    rerender(<DevFlowLogo variant="compact" size={44} title={null} />);
    expect(container.querySelector("svg")).toHaveAttribute("viewBox", MARK.compact.viewBox);
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});
