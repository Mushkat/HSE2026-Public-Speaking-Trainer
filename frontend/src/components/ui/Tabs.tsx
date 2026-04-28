import { ButtonHTMLAttributes } from "react";

import "./Tabs.css";
import { cn } from "./utils";

export type TabItem<T extends string> = {
  key: T;
  label: string;
};

type TabsProps<T extends string> = {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
};

export const Tabs = <T extends string>({ items, value, onChange }: TabsProps<T>) => (
  <div className="ui-tabs" role="tablist" aria-orientation="horizontal">
    {items.map((item) => (
      <TabButton
        key={item.key}
        type="button"
        role="tab"
        aria-selected={value === item.key}
        className={cn("ui-tab", value === item.key && "ui-tab--active")}
        onClick={() => onChange(item.key)}
      >
        {item.label}
      </TabButton>
    ))}
  </div>
);

const TabButton = ({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button className={className} {...props} />
);
