import 'package:flutter/material.dart' hide Text, Container;
import 'package:flutter/material.dart' as material;

// ── LUMINA DESIGN SYSTEM v2.5.0 ──────────────────
// Command Center. Rajdhani + JetBrains Mono.
// No decorative corners or lines.
// Status = one dot + label. Nothing more.

class LC {
  static const bg = Color(0xFF070A0D);
  static const bg2 = Color(0xFF0B0F14);
  static const card = Color(0xFF0F1519);
  static const border = Color(0xFF1A2530);
  static const dim = Color(0xFF3A5060);
  static const text = Color(0xFFB8CCD8);
  static const green = Color(0xFF00FF88);
  static const amber = Color(0xFFFFAA00);
  static const red = Color(0xFFFF3355);
  static const cyan = Color(0xFF00CCFF);

  // Added aliases for backwards compatibility
  static const textDim = dim;
  static const danger = red;
  static const greenDim = Color(0xFF005522);
  static const inactive = border;
  static const bgCard = card;
  static const bgAlt = bg2;
  static const textPri = text;
  static const textPrimary = text;
  static const textFaint = Color(0xFF2A3A45);
  static const greenGlow = green;
  static const bgSecondary = bg2;

  static TextStyle head({
    double size = 14,
    FontWeight? weight,
    FontWeight w = FontWeight.w600,
    Color color = const Color(0xFFB8CCD8),
    double? spacing,
    double letterSpacing = 1.0,
  }) =>
      TextStyle(
        fontFamily: 'Rajdhani',
        fontSize: size,
        fontWeight: weight ?? w,
        color: color,
        letterSpacing: spacing ?? letterSpacing,
        height: 1.2,
      );

  static TextStyle mono({
    double size = 10,
    FontWeight? weight,
    FontWeight w = FontWeight.w400,
    Color color = const Color(0xFF3A5060),
    double? spacing,
    double letterSpacing = 1.5,
  }) =>
      TextStyle(
        fontFamily: 'JetBrainsMono',
        fontSize: size,
        fontWeight: weight ?? w,
        color: color,
        letterSpacing: spacing ?? letterSpacing,
        height: 1.3,
      );
}

// ── STATUS DOT ────────────────────────────────────
enum TermStatus { online, degraded, offline }

class StatusDot extends material.StatefulWidget {
  final dynamic status;
  final double size;
  final material.Color? color;
  final bool? blink;
  const StatusDot(
      {super.key, this.status, this.size = 12, this.color, this.blink});
  @override
  material.State<StatusDot> createState() => _StatusDotState();
}

class _StatusDotState extends material.State<StatusDot>
    with material.SingleTickerProviderStateMixin {
  late material.AnimationController _ctrl;
  late material.Animation<double> _fade;

  @override
  void initState() {
    super.initState();
    _ctrl = material.AnimationController(
        vsync: this, duration: const Duration(milliseconds: 2500));
    _fade = material.Tween(begin: 1.0, end: 0.4).animate(
        material.CurvedAnimation(
            parent: _ctrl, curve: material.Curves.easeInOut));
    final isOnline = widget.status?.toString().endsWith('online') ?? false;
    if (widget.blink == true || isOnline) _ctrl.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(StatusDot old) {
    super.didUpdateWidget(old);
    final isOnline = widget.status?.toString().endsWith('online') ?? false;
    if (widget.blink == true || isOnline) {
      _ctrl.repeat(reverse: true);
    } else {
      _ctrl.stop();
      _ctrl.value = 1.0;
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  material.Color get _color {
    if (widget.color != null) return widget.color!;
    if (widget.status == null) return LC.dim;
    final name = widget.status.toString().split('.').last;
    return switch (name) {
      'online' => LC.green,
      'degraded' => LC.amber,
      _ => LC.red,
    };
  }

  String get _label {
    if (widget.status == null) return 'UNKNOWN';
    final name = widget.status.toString().split('.').last;
    return switch (name) {
      'online' => 'ONLINE',
      'degraded' => 'DEGRADED',
      _ => 'OFFLINE',
    };
  }

  @override
  material.Widget build(material.BuildContext context) {
    final isOnline = widget.status?.toString().endsWith('online') ?? false;
    return material.Row(
      mainAxisSize: material.MainAxisSize.min,
      children: [
        material.AnimatedBuilder(
          animation: _fade,
          builder: (_, __) => material.Opacity(
            opacity: (widget.blink == true || isOnline) ? _fade.value : 1.0,
            child: material.Container(
              width: widget.size,
              height: widget.size,
              decoration: material.BoxDecoration(
                  shape: material.BoxShape.circle,
                  color: _color,
                  boxShadow: [
                    material.BoxShadow(
                        color: _color.withValues(alpha: 0.5),
                        blurRadius: 8,
                        spreadRadius: 1)
                  ]),
            ),
          ),
        ),
        const material.SizedBox(width: 6),
        Text(_label, style: LC.mono(size: 8, color: _color, spacing: 2)),
      ],
    );
  }
}

// ── QUICK ACTION ──────────────────────────────────
class QuickAction extends material.StatefulWidget {
  final String label;
  final bool active;
  final material.VoidCallback? onTap;
  const QuickAction(
      {super.key, required this.label, this.active = false, this.onTap});
  @override
  material.State<QuickAction> createState() => _QuickActionState();
}

class _QuickActionState extends material.State<QuickAction> {
  bool _pressed = false;
  @override
  material.Widget build(material.BuildContext context) {
    final on = widget.active || _pressed;
    return material.GestureDetector(
      onTapDown: (_) => setState(() => _pressed = true),
      onTapUp: (_) {
        setState(() => _pressed = false);
        widget.onTap?.call();
      },
      onTapCancel: () => setState(() => _pressed = false),
      child: material.AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        padding:
            const material.EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: material.BoxDecoration(
          color: on ? LC.green.withValues(alpha: 0.08) : LC.card,
          border: material.Border.all(color: on ? LC.green : LC.border),
          borderRadius: material.BorderRadius.circular(2),
        ),
        child: Text(widget.label,
            style: LC.head(
                size: 11,
                w: material.FontWeight.w600,
                color: on ? LC.green : LC.text,
                spacing: 1.5)),
      ),
    );
  }
}

// ── STAT CARD ─────────────────────────────────────
class StatCard extends material.StatelessWidget {
  final String label;
  final String value;
  final material.Color valueColor;
  final material.Color accentColor;
  final String unit;
  final material.Color? color;
  const StatCard(
      {super.key,
      required this.label,
      required this.value,
      this.valueColor = LC.text,
      this.accentColor = LC.green,
      this.unit = '',
      this.color});

  @override
  material.Widget build(material.BuildContext context) => Container(
        padding: const material.EdgeInsets.all(4),
        decoration: material.BoxDecoration(
          color: LC.card,
          border: material.Border.all(color: LC.border),
          borderRadius: material.BorderRadius.circular(3),
        ),
        child: material.Column(
            crossAxisAlignment: material.CrossAxisAlignment.start,
            children: [
              Text(label, style: LC.mono(size: 7, spacing: 2)),
              const material.SizedBox(height: 4),
              Text(value,
                  style: LC.head(
                      size: 22,
                      w: material.FontWeight.w700,
                      color: valueColor,
                      spacing: 0)),
              const material.SizedBox(height: 4),
              Container(height: 1, color: accentColor.withValues(alpha: 0.5)),
            ]),
      );
}

// ── REVENUE BAR ───────────────────────────────────
class RevenueBar extends material.StatelessWidget {
  final double current;
  final double target;
  const RevenueBar({super.key, required this.current, required this.target});

  @override
  material.Widget build(material.BuildContext context) {
    final pct = (current / target).clamp(0.0, 1.0);
    return Container(
      padding: const material.EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: material.BoxDecoration(
        color: LC.card,
        border: material.Border.all(color: LC.border),
        borderRadius: material.BorderRadius.circular(3),
      ),
      child: material.Column(children: [
        material.Row(
            mainAxisAlignment: material.MainAxisAlignment.spaceBetween,
            children: [
              Text('MAY 9 MISSION',
                  style: LC.head(
                      size: 11,
                      w: material.FontWeight.w600,
                      color: LC.dim,
                      spacing: 2)),
              Text(
                  '\$${current.toStringAsFixed(0)} / \$${target.toStringAsFixed(0)}',
                  style: LC.mono(size: 10, color: LC.green)),
            ]),
        const material.SizedBox(height: 6),
        material.ClipRRect(
          borderRadius: material.BorderRadius.circular(2),
          child: material.LinearProgressIndicator(
            value: pct,
            minHeight: 3,
            backgroundColor: LC.bg2,
            valueColor:
                const material.AlwaysStoppedAnimation<material.Color>(LC.green),
          ),
        ),
      ]),
    );
  }
}

// ── CHAT BUBBLE ───────────────────────────────────
class ChatBubble extends material.StatelessWidget {
  final String text;
  final bool fromLumina;
  const ChatBubble({super.key, required this.text, required this.fromLumina});

  @override
  material.Widget build(material.BuildContext context) => material.Align(
        alignment: fromLumina
            ? material.Alignment.centerLeft
            : material.Alignment.centerRight,
        child: material.Column(
          crossAxisAlignment: fromLumina
              ? material.CrossAxisAlignment.start
              : material.CrossAxisAlignment.end,
          children: [
            Text(fromLumina ? 'LUMINA' : 'YOU',
                style: LC.mono(
                    size: 7,
                    spacing: 2,
                    color: fromLumina ? LC.green : LC.dim)),
            const material.SizedBox(height: 2),
            material.ConstrainedBox(
              constraints: material.BoxConstraints(
                  maxWidth: material.MediaQuery.of(context).size.width * 0.82),
              child: Container(
                padding: const material.EdgeInsets.symmetric(
                    horizontal: 10, vertical: 7),
                decoration: material.BoxDecoration(
                  color: fromLumina ? LC.green.withValues(alpha: 0.06) : LC.bg2,
                  border: material.Border(
                    left: fromLumina
                        ? const material.BorderSide(color: LC.green, width: 2)
                        : material.BorderSide(color: LC.border),
                    right: !fromLumina
                        ? const material.BorderSide(color: LC.cyan, width: 2)
                        : material.BorderSide(color: LC.border),
                    top: material.BorderSide(color: LC.border),
                    bottom: material.BorderSide(color: LC.border),
                  ),
                  borderRadius: material.BorderRadius.circular(2),
                ),
                child: Text(text,
                    style: LC.head(
                        size: 13,
                        w: material.FontWeight.w400,
                        color: LC.text,
                        spacing: 0.3)),
              ),
            ),
          ],
        ),
      );
}

// ── TYPING INDICATOR ──────────────────────────────
class TypingIndicator extends material.StatefulWidget {
  const TypingIndicator({super.key});
  @override
  material.State<TypingIndicator> createState() => _TypingState();
}

class _TypingState extends material.State<TypingIndicator>
    with material.TickerProviderStateMixin {
  late List<material.AnimationController> _c;
  late List<material.Animation<double>> _a;

  @override
  void initState() {
    super.initState();
    _c = List.generate(
        3,
        (i) => material.AnimationController(
            vsync: this, duration: const Duration(milliseconds: 600))
          ..repeat(
              reverse: true, period: Duration(milliseconds: 1200 + i * 200)));
    _a =
        _c.map((c) => material.Tween(begin: 0.2, end: 1.0).animate(c)).toList();
  }

  @override
  void dispose() {
    for (final c in _c) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  material.Widget build(material.BuildContext context) => material.Align(
        alignment: material.Alignment.centerLeft,
        child: Container(
          padding:
              const material.EdgeInsets.symmetric(horizontal: 10, vertical: 8),
          decoration: material.BoxDecoration(
            color: LC.green.withValues(alpha: 0.04),
            border: material.Border(
              left: const material.BorderSide(color: LC.green, width: 2),
              top: material.BorderSide(color: LC.border),
              bottom: material.BorderSide(color: LC.border),
              right: material.BorderSide(color: LC.border),
            ),
            borderRadius: material.BorderRadius.circular(2),
          ),
          child:
              material.Row(mainAxisSize: material.MainAxisSize.min, children: [
            ...List.generate(
                3,
                (i) => material.AnimatedBuilder(
                      animation: _a[i],
                      builder: (_, __) => material.Opacity(
                        opacity: _a[i].value,
                        child: Container(
                          margin:
                              material.EdgeInsets.only(right: i < 2 ? 4 : 0),
                          width: 5,
                          height: 5,
                          decoration: const material.BoxDecoration(
                              shape: material.BoxShape.circle, color: LC.green),
                        ),
                      ),
                    )),
          ]),
        ),
      );
}

// ── NAV BAR ───────────────────────────────────────
class LuminaNavBar extends material.StatelessWidget {
  final int current;
  final Function(int) onTap;
  const LuminaNavBar({super.key, required this.current, required this.onTap});

  static const _items = [
    (icon: material.Icons.chat_bubble_outline, label: 'CHAT'),
    (icon: material.Icons.grid_view_sharp, label: 'DASHBOARD'),
    (icon: material.Icons.phone_android_outlined, label: 'LOCAL'),
    (icon: material.Icons.notifications_outlined, label: 'ALERTS'),
    (icon: material.Icons.more_horiz, label: 'MORE'),
  ];

  @override
  material.Widget build(material.BuildContext context) => Container(
        decoration: material.BoxDecoration(
          color: LC.bg2,
          border: material.Border(top: material.BorderSide(color: LC.border)),
        ),
        padding: material.EdgeInsets.only(
          top: 6,
          bottom: material.MediaQuery.of(context).padding.bottom + 6,
        ),
        child: material.Row(
          children: List.generate(_items.length, (i) {
            final on = i == current;
            final item = _items[i];
            return material.Expanded(
              child: material.GestureDetector(
                onTap: () => onTap(i),
                behavior: material.HitTestBehavior.opaque,
                child: material.Column(
                    mainAxisSize: material.MainAxisSize.min,
                    children: [
                      material.Icon(item.icon,
                          size: 20, color: on ? LC.green : LC.dim),
                      const material.SizedBox(height: 2),
                      Text(item.label,
                          style: LC.head(
                              size: 8,
                              w: material.FontWeight.w600,
                              color: on ? LC.green : LC.dim,
                              spacing: 1.5)),
                    ]),
              ),
            );
          }),
        ),
      );
}

// ── LC BUTTON ─────────────────────────────────────
class LCButton extends material.StatelessWidget {
  final String label;
  final material.IconData? icon;
  final material.VoidCallback? onPressed;
  final material.Color color;
  final bool loading;
  final bool small;
  const LCButton(
      {super.key,
      required this.label,
      this.icon,
      this.onPressed,
      this.color = LC.green,
      this.loading = false,
      this.small = false});

  @override
  material.Widget build(material.BuildContext context) =>
      material.GestureDetector(
        onTap: onPressed,
        child: Container(
          padding:
              const material.EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: material.BoxDecoration(
            color: color.withValues(alpha: 0.08),
            border: material.Border.all(color: color.withValues(alpha: 0.4)),
            borderRadius: material.BorderRadius.circular(2),
          ),
          child:
              material.Row(mainAxisSize: material.MainAxisSize.min, children: [
            if (icon != null) ...[
              material.Icon(icon, color: color, size: 14),
              const material.SizedBox(width: 6),
            ],
            Text(label,
                style: LC.head(
                    size: 12,
                    w: material.FontWeight.w600,
                    color: color,
                    spacing: 2)),
          ]),
        ),
      );
}

// ── SECTION LABEL ─────────────────────────────────
class SectionLabel extends material.StatelessWidget {
  final String? title;
  final String? subtitle;
  const SectionLabel(this.title, {super.key, this.subtitle});

  @override
  material.Widget build(material.BuildContext context) {
    final t = title ?? '';
    return material.Padding(
      padding: const material.EdgeInsets.only(top: 24, bottom: 12),
      child: material.Row(
        children: [
          material.Text(t, style: LC.head(size: 16)),
          if (subtitle != null) ...[
            const material.SizedBox(width: 12),
            material.Text(subtitle!, style: LC.mono(color: LC.dim)),
          ]
        ],
      ),
    );
  }
}

class AlertBadge extends material.StatelessWidget {
  final int count;
  const AlertBadge(this.count, {super.key});
  @override
  material.Widget build(material.BuildContext context) {
    if (count == 0) return const material.SizedBox.shrink();
    return Container(
      width: 18,
      height: 18,
      decoration: const material.BoxDecoration(
          color: LC.red, shape: material.BoxShape.circle),
      child: material.Center(
          child: Text('$count',
              style:
                  LC.mono(size: 9, color: material.Colors.white, spacing: 0))),
    );
  }
}

// ── COMPATIBILITY WIDGETS ─────────────────────────
class TPanel extends material.StatelessWidget {
  final material.Widget child;
  const TPanel({super.key, required this.child});
  @override
  material.Widget build(material.BuildContext context) => child;
}

class ScanLineOverlay extends material.StatelessWidget {
  final material.Widget? child;
  const ScanLineOverlay({super.key, this.child});
  @override
  material.Widget build(material.BuildContext context) =>
      child ?? const material.SizedBox.shrink();
}

class BlinkingCursor extends material.StatelessWidget {
  const BlinkingCursor({super.key});
  @override
  material.Widget build(material.BuildContext context) =>
      const material.SizedBox.shrink();
}

class TProgressBar extends material.StatelessWidget {
  final double value;
  final material.Color? color;
  const TProgressBar({super.key, required this.value, this.color});
  @override
  material.Widget build(material.BuildContext context) =>
      material.LinearProgressIndicator(value: value, color: color ?? LC.green);
}

class TDangerButton extends material.StatelessWidget {
  final String label;
  final material.VoidCallback? onPressed;
  final material.VoidCallback? onTap;
  final material.VoidCallback? onConfirmed;
  final String? confirmLabel;
  final material.Color? color;
  const TDangerButton(
      {super.key,
      required this.label,
      this.onPressed,
      this.onTap,
      this.onConfirmed,
      this.confirmLabel,
      this.color});
  @override
  material.Widget build(material.BuildContext context) => LCButton(
      label: label,
      icon: material.Icons.warning,
      onPressed: onPressed ?? onTap ?? onConfirmed ?? () {},
      color: color ?? LC.danger);
}

class TLogViewer extends material.StatelessWidget {
  final List<String>? logs;
  final List<String>? lines;
  final double? height;
  const TLogViewer({super.key, this.logs, this.lines, this.height});
  @override
  material.Widget build(material.BuildContext context) {
    final list = logs ?? lines ?? [];
    return material.SizedBox(
        height: height ?? 200,
        child: material.ListView(
            children:
                list.map((l) => material.Text(l, style: LC.mono())).toList()));
  }
}

// DELETED TTEXT
class TText extends material.StatelessWidget {
  final String data;
  final material.Color? color;
  final double? size;
  final material.FontWeight? weight;
  final double? letterSpacing;
  final material.TextAlign? align;
  const TText(this.data,
      {super.key,
      this.color,
      this.size,
      this.weight,
      this.letterSpacing,
      this.align});
  @override
  material.Widget build(material.BuildContext context) => Text(data,
      textAlign: align,
      style: LC.head(
          color: color ?? LC.text,
          size: size ?? 14,
          w: weight ?? material.FontWeight.w600,
          spacing: letterSpacing ?? 1.0));
}

class TButton extends material.StatelessWidget {
  final String label;
  final material.VoidCallback? onPressed;
  final material.VoidCallback? onTap;
  final material.IconData? icon;
  final bool? loading;
  final material.Color? color;
  const TButton(
      {super.key,
      required this.label,
      this.onPressed,
      this.onTap,
      this.icon,
      this.loading,
      this.color});
  @override
  material.Widget build(material.BuildContext context) => LCButton(
      label: label,
      icon: icon,
      onPressed: onPressed ?? onTap ?? () {},
      color: color ?? LC.green);
}

class TC {
  static const green = LC.green;
  static const error = LC.red;
  static const danger = LC.danger;
  static const text = LC.text;
  static const dim = LC.dim;
  static const textDim = LC.textDim;
  static const textFaint = LC.textFaint;
  static const greenDim = LC.greenDim;
  static const bg = LC.bg;
  static const bgAlt = LC.bg2;
}

// ── SHADOWED FLUTTER PRIMITIVES ────────────────────
class Text extends StatelessWidget {
  final String data;
  final Color? color;
  final double? size;
  final FontWeight? weight;
  final double? spacing;
  final double? letterSpacing;
  final TextAlign? textAlign;
  final TextStyle? style;
  final TextOverflow? overflow;
  final int? maxLines;

  const Text(this.data,
      {super.key,
      this.color,
      this.size,
      this.weight,
      this.spacing,
      this.letterSpacing,
      this.textAlign,
      this.style,
      this.overflow,
      this.maxLines});

  @override
  Widget build(BuildContext context) => material.Text(data,
      textAlign: textAlign,
      overflow: overflow,
      maxLines: maxLines,
      style: style ??
          LC.head(
              color: color ?? LC.text,
              size: size ?? 14,
              w: weight ?? FontWeight.w600,
              spacing: spacing ?? letterSpacing ?? 1.0));
}

class Container extends StatelessWidget {
  final Widget? child;
  final String? label;
  final Widget? trailing;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final Decoration? decoration;
  final double? width;
  final double? height;
  final AlignmentGeometry? alignment;
  final Color? color;

  const Container(
      {super.key,
      this.child,
      this.label,
      this.trailing,
      this.padding,
      this.margin,
      this.decoration,
      this.width,
      this.height,
      this.alignment,
      this.color});

  @override
  Widget build(BuildContext context) {
    if (label != null || trailing != null) {
      return material.Container(
          padding: padding ?? const EdgeInsets.all(12),
          margin: margin ?? const EdgeInsets.only(bottom: 12),
          decoration: decoration ??
              BoxDecoration(
                  color: LC.card,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: LC.border)),
          width: width,
          height: height,
          alignment: alignment,
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(children: [
                  if (label != null)
                    Text(label!, style: LC.head(size: 10, color: LC.green)),
                  if (trailing != null) ...[const Spacer(), trailing!]
                ]),
                if (label != null || trailing != null)
                  const SizedBox(height: 10),
                if (child != null)
                  CustomPaint(painter: _DrawContent(), child: child!),
              ]));
    }
    return material.Container(
        padding: padding,
        margin: margin,
        decoration: decoration,
        width: width,
        height: height,
        alignment: alignment,
        color: color,
        child: child);
  }
}

class _DrawContent extends CustomPainter {
  @override
  void paint(Canvas c, Size s) {}
  @override
  bool shouldRepaint(covariant CustomPainter old) => false;
}
