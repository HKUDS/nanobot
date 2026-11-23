import { ImageViewport } from "@/components/ui/image-viewport";

/** Photo lightbox layout; the gallery retains ownership of the arrow keys. */
export function ZoomableImage({ src, alt }: { src: string; alt: string }) {
  return <ImageViewport
    src={src}
    alt={alt}
    testId="image-zoom-viewport"
    panWithArrows={false}
    className="absolute inset-x-3 bottom-[calc(4rem+env(safe-area-inset-bottom))] top-14 focus-visible:ring-white/40 sm:inset-x-8"
    imageClassName="rounded-compact shadow-2xl"
    controlsClassName="absolute bottom-[calc(1rem+env(safe-area-inset-bottom))] left-1/2 -translate-x-1/2 bg-black/55 text-white/90 backdrop-blur-sm [&_button:first-child:hover]:text-white [&_button:last-child:hover]:text-white [&_button:focus-visible]:ring-white/70"
  />;
}
