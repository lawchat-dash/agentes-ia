'use client';

/*
 * TextType (React Bits, TextAnimations/TextType), reescrito SEM gsap (o painel não tem gsap):
 *  - a piscada do cursor é animação CSS (text-type__blink, ver TextType.css);
 *  - o cursor fica logo depois do texto (sem o deslize com gsap);
 *  - mesma máquina de digitar/apagar, com efeito por letra (fade, blur, rise) pela Web Animations API;
 *  - prefers-reduced-motion: mostra a frase inteira, sem digitar e sem piscar.
 * Leitores de tela leem o texto inteiro (text-type__sr); a parte animada fica aria-hidden.
 */

import { type ElementType, createElement, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './TextType.css';

interface TextTypeProps {
  className?: string;
  showCursor?: boolean;
  hideCursorWhileTyping?: boolean;
  cursorStyle?: 'character' | 'bar' | 'block' | 'underscore';
  cursorCharacter?: string | React.ReactNode;
  cursorColor?: string;
  cursorBlinkDuration?: number;
  cursorClassName?: string;
  text: string | string[];
  as?: ElementType;
  typingSpeed?: number;
  initialDelay?: number;
  pauseDuration?: number;
  deletingSpeed?: number;
  typeEffect?: 'none' | 'fade' | 'blur' | 'rise';
  prefix?: string;
  loop?: boolean;
  textColors?: string[];
  variableSpeed?: { min: number; max: number };
  onSentenceComplete?: (sentence: string, index: number) => void;
  startOnVisible?: boolean;
  /** Para de piscar o cursor (e o esconde) quando a última frase termina, se não houver loop. */
  hideCursorOnDone?: boolean;
}

type Effect = { keyframes: Keyframe[]; options: KeyframeAnimationOptions };

const EFFECTS: Record<'fade' | 'blur' | 'rise', Effect> = {
  fade: {
    keyframes: [{ opacity: 0 }, { opacity: 1 }],
    options: { duration: 360, easing: 'cubic-bezier(0.25, 1, 0.5, 1)' }
  },
  blur: {
    keyframes: [
      { opacity: 0, filter: 'blur(0.3em)' },
      { opacity: 1, filter: 'blur(0em)' }
    ],
    options: { duration: 520, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  },
  rise: {
    keyframes: [
      { opacity: 0, top: '0.6em' },
      { opacity: 1, top: '0em' }
    ],
    options: { duration: 480, easing: 'cubic-bezier(0.34, 1.4, 0.64, 1)' }
  }
};

const graphemes = (value: string): string[] => {
  if (typeof Intl !== 'undefined' && (Intl as any).Segmenter) {
    return Array.from(new (Intl as any).Segmenter(undefined, { granularity: 'grapheme' }).segment(value), (part: any) => part.segment as string);
  }
  return Array.from(value);
};

const TextType = ({
  text,
  as: Component = 'div',
  typingSpeed = 50,
  initialDelay = 0,
  pauseDuration = 2000,
  deletingSpeed = 30,
  loop = true,
  className = '',
  showCursor = true,
  hideCursorWhileTyping = false,
  hideCursorOnDone = false,
  cursorStyle = 'character',
  cursorCharacter = '|',
  cursorColor = 'currentColor',
  cursorClassName = '',
  cursorBlinkDuration = 0.5,
  typeEffect = 'none',
  prefix = '',
  textColors = [],
  variableSpeed,
  onSentenceComplete,
  startOnVisible = false,
  ...props
}: TextTypeProps & React.HTMLAttributes<HTMLElement>) => {
  const [textIndex, setTextIndex] = useState(0);
  const [count, setCount] = useState(0);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isVisible, setIsVisible] = useState(!startOnVisible);
  const [reduceMotion, setReduceMotion] = useState(
    () => typeof window !== 'undefined' && (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  );
  const containerRef = useRef<HTMLElement>(null);
  const onSentenceCompleteRef = useRef(onSentenceComplete);

  const textKey = Array.isArray(text) ? text.join('\u0000') : String(text ?? '');
  const textArray = useMemo(() => textKey.split('\u0000'), [textKey]);
  const index = textIndex % textArray.length;
  const chars = useMemo(() => graphemes(textArray[index]), [textArray, index]);
  const total = chars.length;
  const shown = reduceMotion ? total : Math.min(count, total);
  const minSpeed = variableSpeed?.min ?? typingSpeed;
  const maxSpeed = variableSpeed?.max ?? typingSpeed;

  useEffect(() => {
    onSentenceCompleteRef.current = onSentenceComplete;
  }, [onSentenceComplete]);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduceMotion(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!startOnVisible || !containerRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        setIsVisible(true);
        observer.disconnect();
      },
      { threshold: 0.1 }
    );
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, [startOnVisible]);

  useEffect(() => {
    if (!isVisible || reduceMotion) return;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const wait = (ms: number, next: () => void) => {
      timeout = setTimeout(next, ms);
    };
    const speed = () => minSpeed + Math.random() * (maxSpeed - minSpeed);

    if (!isDeleting) {
      if (shown < total) {
        const lead = shown === 0 ? initialDelay : 0;
        wait(lead + speed(), () => setCount(shown + 1));
      } else if (loop || index < textArray.length - 1) {
        wait(pauseDuration, () => setIsDeleting(true));
      } else {
        onSentenceCompleteRef.current?.(textArray[index], index);
      }
    } else if (shown > 0) {
      wait(deletingSpeed, () => setCount(shown - 1));
    } else {
      onSentenceCompleteRef.current?.(textArray[index], index);
      setIsDeleting(false);
      setTextIndex((index + 1) % textArray.length);
    }
    return () => clearTimeout(timeout);
  }, [isVisible, isDeleting, shown, total, index, textArray, loop, deletingSpeed, pauseDuration, initialDelay, minSpeed, maxSpeed, reduceMotion]);

  const animateChar = useCallback(
    (node: HTMLSpanElement | null) => {
      const effect = typeEffect === 'none' ? undefined : EFFECTS[typeEffect];
      if (!node || !effect || reduceMotion || typeof node.animate !== 'function') return;
      node.animate(effect.keyframes, effect.options);
    },
    [typeEffect, reduceMotion]
  );

  const color = textColors.length ? textColors[index % textColors.length] : 'inherit';
  const typing = shown < total || isDeleting;
  const done = !typing && !loop && index === textArray.length - 1;
  const hideCursor = (hideCursorWhileTyping && typing) || (hideCursorOnDone && done) || (reduceMotion && hideCursorOnDone);
  const cursorCss = {
    ...(cursorColor && cursorColor !== 'currentColor' ? { color: cursorColor } : {}),
    ['--tt-blink' as any]: `${Math.max(0.2, cursorBlinkDuration * 2)}s`
  };

  return createElement(
    Component,
    { ref: containerRef, className: `text-type ${className}`, ...props },
    <span className="text-type__sr">{prefix + textArray.join(' ')}</span>,
    <span className="text-type__content" aria-hidden="true">
      {prefix ? <span className="text-type__prefix">{prefix}</span> : null}
      <span style={{ color }}>
        {chars.slice(0, shown).map((char, i) => (
          <span key={i} ref={animateChar} className="text-type__char">
            {char}
          </span>
        ))}
      </span>
      {showCursor && (
        <span
          aria-hidden="true"
          className={`text-type__cursor-inline text-type__cursor--${cursorStyle} ${hideCursor ? 'text-type__cursor--hidden' : ''} ${cursorClassName}`}
          style={cursorCss}
        >
          <span className={`text-type__blink${reduceMotion ? '' : ' text-type__blink--anim'}`}>
            {cursorStyle === 'character' ? cursorCharacter : <span className="text-type__shape" />}
          </span>
        </span>
      )}
    </span>
  );
};

export default TextType;
