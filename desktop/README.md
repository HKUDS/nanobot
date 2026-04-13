# Tauri + shadcn/ui + Tailwind CSS Boilerplate

A simple desktop app boilerplate with Tauri v2, shadcn/ui, and Tailwind CSS.

## Tech Stack

- **Tauri v2** - Desktop app framework
- **React 18** - Frontend library  
- **TypeScript** - Type safety
- **shadcn/ui** - UI components
- **Tailwind CSS** - Styling
- **Vite** - Build tool

## Quick Start

### Prerequisites
- [Bun](https://bun.sh/) or [Node.js](https://nodejs.org/) 18+
- [Rust](https://rustup.rs/)

### Installation

```bash
# Clone the repository
git clone https://github.com/wabisabi9547/tauri-shadcn-tailwind-boilerplate.git
cd tauri-shadcn-tailwind-boilerplate

# Install dependencies
bun install

# Start development
bun run tauri:dev

# Build for production
bun run tauri:build
```

## Project Structure

```
src/
├── components/ui/     # shadcn/ui components
├── App.tsx           # Main component
├── main.tsx          # React entry
└── index.css         # Global styles

src-tauri/            # Tauri backend
├── src/              # Rust code
├── Cargo.toml        # Rust deps
└── tauri.conf.json   # Tauri config
```

## Adding Components

```bash
# Add shadcn/ui components
bunx shadcn@latest add button
bunx shadcn@latest add card
```

## License

MIT
