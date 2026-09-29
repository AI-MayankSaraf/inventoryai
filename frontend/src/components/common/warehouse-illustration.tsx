import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Wide line-art godown scene used along the bottom of the login brand panel.
 * Strokes inherit currentColor so it sits quietly on the navy background.
 */
export function WarehouseIllustration({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 900 300"
      fill="none"
      preserveAspectRatio="xMidYMax meet"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("w-full", className)}
      aria-hidden="true"
    >
      <g
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.6"
      >
        {/* ---------- Rack A ---------- */}
        <g opacity="0.85">
          <path d="M40 96v186M196 96v186" />
          <path d="M40 96h156M40 158h156M40 220h156M40 282h156" />
        </g>
        <g opacity="0.62">
          <rect x="56" y="112" width="58" height="44" rx="3" />
          <path d="M56 128h58" />
          <path d="M85 112v16" />
          <rect x="124" y="122" width="42" height="34" rx="3" />
          <rect x="172" y="118" width="18" height="38" rx="3" />
          <rect x="56" y="176" width="46" height="42" rx="3" />
          <rect x="112" y="184" width="66" height="34" rx="3" />
          <path d="M112 197h66" />
          <path d="M145 184v13" />
          <rect x="62" y="240" width="70" height="40" rx="3" />
          <path d="M62 255h70" />
          <rect x="142" y="234" width="48" height="46" rx="3" />
        </g>

        {/* ---------- Rack B (taller, centre) ---------- */}
        <g opacity="0.9">
          <path d="M262 54v228M418 54v228" />
          <path d="M262 54h156M262 130h156M262 206h156M262 282h156" />
        </g>
        <g opacity="0.66">
          <rect x="278" y="74" width="54" height="54" rx="3" />
          <path d="M278 92h54" />
          <path d="M305 74v18" />
          <rect x="342" y="86" width="40" height="42" rx="3" />
          <rect x="392" y="80" width="20" height="48" rx="3" />
          <rect x="278" y="152" width="68" height="52" rx="3" />
          <path d="M278 170h68" />
          <path d="M312 152v18" />
          <rect x="356" y="164" width="56" height="40" rx="3" />
          <path d="M356 176h56" />
          <rect x="272" y="228" width="58" height="52" rx="3" />
          <rect x="340" y="220" width="72" height="60" rx="3" />
          <path d="M340 240h72" />
          <path d="M376 220v20" />
        </g>

        {/* ---------- Rack C ---------- */}
        <g opacity="0.85">
          <path d="M484 110v172M640 110v172" />
          <path d="M484 110h156M484 172h156M484 234h156M484 282h156" />
        </g>
        <g opacity="0.6">
          <rect x="500" y="126" width="62" height="44" rx="3" />
          <path d="M500 142h62" />
          <path d="M531 126v16" />
          <rect x="572" y="136" width="34" height="34" rx="3" />
          <rect x="616" y="130" width="18" height="40" rx="3" />
          <rect x="498" y="190" width="46" height="42" rx="3" />
          <rect x="554" y="184" width="80" height="48" rx="3" />
          <path d="M554 202h80" />
          <path d="M594 184v18" />
          <rect x="504" y="246" width="60" height="34" rx="3" />
          <rect x="574" y="252" width="52" height="28" rx="3" />
        </g>

        {/* ---------- Rack D (partial, right edge) ---------- */}
        <g opacity="0.7">
          <path d="M706 140v142M862 140v142" />
          <path d="M706 140h156M706 202h156M706 264h156" />
        </g>
        <g opacity="0.5">
          <rect x="722" y="156" width="54" height="46" rx="3" />
          <path d="M722 172h54" />
          <rect x="788" y="166" width="56" height="36" rx="3" />
          <rect x="722" y="218" width="72" height="46" rx="3" />
          <path d="M722 234h72" />
          <rect x="806" y="226" width="42" height="38" rx="3" />
        </g>

        {/* ---------- Floor + foreground pallets ---------- */}
        <path d="M0 282h900" opacity="0.9" />
        <g opacity="0.45">
          <path d="M214 282v-22h30v22M214 268h30" />
          <path d="M440 282v-30h36v30M440 264h36" />
          <path d="M660 282v-18h26v18M660 272h26" />
        </g>

        {/* ---------- Overhead beams ---------- */}
        <g opacity="0.3">
          <path d="M0 26h900" />
          <path d="M120 26v14M340 26v14M560 26v14M780 26v14" />
        </g>
      </g>
    </svg>
  );
}
