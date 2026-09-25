import { cn } from "@/utils/cn";

/** The capybara ranger. Decorative: the surrounding copy carries the meaning. */
export const Mascot = ({ size = 132, className }: { size?: number; className?: string }) => (
  <img
    src="/mascot.png"
    width={size}
    height={size}
    alt=""
    aria-hidden="true"
    draggable={false}
    decoding="async"
    className={cn("mascot", className)}
  />
);

/** The ranger's head, used as the product mark. */
export const BrandMark = ({ size = 28 }: { size?: number }) => (
  <img
    src="/logo.png"
    width={size}
    height={size}
    alt=""
    aria-hidden="true"
    className="brand-mark"
  />
);
