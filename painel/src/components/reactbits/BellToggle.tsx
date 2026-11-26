'use client';

/*
 * BellToggle (React Bits, Micro/BellToggle), adaptado ao sino do topo do painel:
 *  - só o sino (sem o botão com texto "Notify me"): quem usa põe dentro do próprio botão/link;
 *  - sem motion/react: o balanço, o badalo e as ondas são Web Animations API, como no original;
 *  - toca quando `count` sobe (chegou aviso novo) e quando `tocar` muda; com movimento reduzido, não balança;
 *  - ícone padrão do lucide-react (Bell) no lugar do @hugeicons; selo com a contagem ("9+" acima de 9).
 */

import React, { useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { Bell } from 'lucide-react';
import './BellToggle.css';

export interface BellToggleProps {
  icon?: ReactNode;
  count?: number;
  badge?: boolean;
  badgeColor?: string;
  badgeTextColor?: string;
  waves?: boolean;
  clapper?: boolean;
  iconSize?: number;
  ringAmplitude?: number;
  ringPasses?: number;
  ringDecay?: number;
  ringDuration?: number;
  ringPivot?: number;
  /** Qualquer valor novo faz o sino tocar uma vez (ex.: um contador de "tocar agora"). */
  tocar?: number | string;
  className?: string;
}

const SEG_EASE = 'cubic-bezier(0.77, 0, 0.175, 1)';
const WARP = 0.6;
const BELL_BODY = 'M6 16.5V10a6 6 0 0 1 12 0v6.5l1.6 2.3H4.4L6 16.5z';

const passOffset = (k: number, passes: number) => 1 - Math.pow(1 - (k + 2 / 3) / (passes + 1), WARP);
const ringKeyframes = (from: number, amplitude: number, passes: number, decay: number): Keyframe[] => {
  const frames: Keyframe[] = [{ transform: `rotate(${from}deg)`, offset: 0, easing: SEG_EASE }];
  for (let k = 0; k < passes; k++) {
    const angle = amplitude * Math.pow(1 - k / passes, decay) * (k % 2 ? 1 : -1);
    frames.push({ transform: `rotate(${angle.toFixed(2)}deg)`, offset: passOffset(k, passes), easing: SEG_EASE });
  }
  frames.push({ transform: 'rotate(0deg)', offset: 1 });
  return frames;
};
const liveAngle = (el: Element) => {
  const tf = getComputedStyle(el).transform;
  if (!tf || tf === 'none') return 0;
  const m = new DOMMatrix(tf);
  return (Math.atan2(m.b, m.a) * 180) / Math.PI;
};
const prefersReduced = () =>
  typeof window !== 'undefined' && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false);

const BellToggle: React.FC<BellToggleProps> = ({
  icon,
  count = 0,
  badge = true,
  badgeColor = '#DC2626',
  badgeTextColor = '#ffffff',
  waves = true,
  clapper = false,
  iconSize = 18,
  ringAmplitude = 17,
  ringPasses = 5,
  ringDecay = 1,
  ringDuration = 820,
  ringPivot = 16,
  tocar,
  className = ''
}) => {
  const glyphRef = useRef<HTMLSpanElement>(null);
  const clapperRef = useRef<HTMLSpanElement>(null);
  const waveLeft = useRef<SVGSVGElement>(null);
  const waveRight = useRef<SVGSVGElement>(null);
  const prevCount = useRef(0);
  const primeiroTocar = useRef(true);

  const swing = (amplitude: number, passes: number, duration: number) => {
    const el = glyphRef.current;
    if (!el || prefersReduced() || typeof el.animate !== 'function') return;
    el.getAnimations().forEach(a => a.cancel());
    el.animate(ringKeyframes(liveAngle(el), amplitude, passes, ringDecay), { duration, easing: 'linear' });
    const c = clapperRef.current;
    if (c) {
      c.getAnimations().forEach(a => a.cancel());
      c.animate(ringKeyframes(liveAngle(c), amplitude * 1.6, passes, ringDecay), { duration, delay: 70, easing: 'linear' });
    }
    if (!waves) return;
    for (let k = 0; k < passes; k++) {
      const side = k % 2 ? waveRight.current : waveLeft.current;
      if (!side) continue;
      const strength = Math.pow(1 - k / passes, ringDecay);
      side.animate(
        [
          { opacity: 0, transform: 'scale(0.55)' },
          { opacity: 0.9 * strength, offset: 0.3 },
          { opacity: 0, transform: 'scale(1.25)' }
        ],
        { duration: 380, delay: passOffset(k, passes) * duration, easing: 'ease-out' }
      );
    }
  };

  // Chegou aviso novo (a contagem subiu): toca inteiro. A primeira carga com avisos também toca.
  useEffect(() => {
    const was = prevCount.current;
    prevCount.current = count;
    if (count > was) swing(ringAmplitude, ringPasses, ringDuration);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);

  useEffect(() => {
    if (primeiroTocar.current) {
      primeiroTocar.current = false;
      return;
    }
    if (tocar !== undefined) swing(ringAmplitude * 0.6, 3, 520);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tocar]);

  const showBadge = badge && count > 0;

  return (
    <span
      className={`bell-toggle bell-toggle--icone${className ? ` ${className}` : ''}`}
      style={{ '--bt-badge': badgeColor, '--bt-badge-ink': badgeTextColor, '--bt-pivot': `${ringPivot}%`, '--bt-icon': `${iconSize}px` } as CSSProperties}
    >
      <span className="bell-toggle__bell" aria-hidden="true">
        <span ref={glyphRef} className="bell-toggle__glyph">
          {clapper ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d={BELL_BODY} />
              <path d="M12 2.5V4" />
            </svg>
          ) : (
            (icon ?? <Bell size={iconSize} strokeWidth={2} />)
          )}
        </span>
        {clapper ? (
          <span ref={clapperRef} className="bell-toggle__clapper">
            <svg viewBox="0 0 24 24">
              <circle cx="12" cy="20.4" r="1.7" fill="currentColor" />
            </svg>
          </span>
        ) : null}
        {waves ? (
          <>
            <svg ref={waveLeft} className="bell-toggle__wave bell-toggle__wave--left" viewBox="0 0 14 14">
              <path d="M14 8a6 6 0 0 0-6 6" />
              <path d="M14 4A10 10 0 0 0 4 14" />
            </svg>
            <svg ref={waveRight} className="bell-toggle__wave bell-toggle__wave--right" viewBox="0 0 14 14">
              <path d="M0 8a6 6 0 0 1 6 6" />
              <path d="M0 4a10 10 0 0 1 10 10" />
            </svg>
          </>
        ) : null}
        {badge ? (
          <span className="bell-toggle__badge" data-show={showBadge ? '' : undefined}>
            <span key={count} className="bell-toggle__digit">
              {count > 9 ? '9+' : count}
            </span>
          </span>
        ) : null}
      </span>
    </span>
  );
};

export default BellToggle;
