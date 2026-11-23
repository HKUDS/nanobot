# 行内公式

这是行内公式：\(E = mc^2\)。

这是另一种行内公式：$a^2+b^2=c^2$。

---

# 独立公式

\[
\int_{-\infty}^{\infty} e^{-x^2}\,dx=\sqrt{\pi}
\]

$$
\sum_{i=1}^{n} i=\frac{n(n+1)}{2}
$$

---

# 分行公式

\[
\begin{aligned}
f(x)
&= x^2+2x+1 \\
&= (x+1)^2
\end{aligned}
\]

---

# 多行等式

\[
\begin{aligned}
a &= b+c \\
  &= d+e \\
  &= f
\end{aligned}
\]

---

# 分情况公式

\[
f(x)=
\begin{cases}
x^2, & x\ge 0,\\
-x, & x<0.
\end{cases}
\]

---

# 矩阵

\[
A=
\begin{pmatrix}
1 & 2 & 3\\
4 & 5 & 6\\
7 & 8 & 9
\end{pmatrix}
\]

\[
\begin{bmatrix}
a & b\\
c & d
\end{bmatrix}
\]

---

# 行列式

\[
\det(A)=
\begin{vmatrix}
a & b\\
c & d
\end{vmatrix}
=ad-bc
\]

---

# 分数与根式

\[
x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}
\]

---

# 极限、导数与积分

\[
\lim_{x\to 0}\frac{\sin x}{x}=1
\]

\[
\frac{d}{dx}\left(\ln x\right)=\frac{1}{x}
\]

\[
\int_a^b f(x)\,dx=F(b)-F(a)
\]

---

# 向量与范数

\[
\vec{v}=
\begin{bmatrix}
v_1\\
v_2\\
v_3
\end{bmatrix},
\qquad
\|\vec{v}\|_2=
\sqrt{v_1^2+v_2^2+v_3^2}
\]

---

# 概率

\[
P(A\mid B)=\frac{P(B\mid A)P(A)}{P(B)}
\]

\[
X\sim\mathcal{N}(\mu,\sigma^2)
\]

---

# 逻辑与集合

\[
\forall x\in\mathbb{R},\quad x^2\ge 0
\]

\[
A\subseteq B,\qquad
A\cap B=\varnothing,\qquad
A\cup B
\]

---

# 颜色与字体

\[
\color{red}{\text{红色文字}}
\qquad
\mathbf{bold}
\qquad
\mathit{italic}
\qquad
\mathrm{Roman}
\]

---

# 上标与下标

\[
x_1,x_2,\ldots,x_n
\qquad
e^{i\pi}+1=0
\]

---

# 大型运算符

\[
\left(\sum_{i=1}^{n}x_i\right)^2
\qquad
\prod_{k=1}^{m} k
\qquad
\bigcup_{i=1}^{n} A_i
\]

---

# 物理公式

\[
\mathrm{HFOV}=2\arctan\left(\frac{W}{2f_x}\right)
\]

\[
F=ma,\qquad
p=mv,\qquad
E=h\nu
\]

---

# 化学与单位

\[
\mathrm{H_2O},\qquad
\mathrm{CO_2},\qquad
\mathrm{C_6H_{12}O_6}
\]

\[
9.8\,\mathrm{m\,s^{-2}}
\qquad
3.0\times10^8\,\mathrm{m/s}
\]

---

# Markdown 列表中的公式

1. $x=1$
2. $y=2$

- \(\alpha+\beta=\gamma\)
- \(\Delta x\to 0\)
- \(\nabla\cdot\vec{E}=\frac{\rho}{\varepsilon_0}\)

---

# 引用中的公式

> 公式：\[
> \hat{y}=\sigma(Wx+b)
> \]

---

# 表格中的公式

| 名称 | 公式 |
|---|---|
| 欧拉公式 | \(e^{i\pi}+1=0\) |
| 勾股定理 | \(a^2+b^2=c^2\) |
| 透视关系 | \(\displaystyle y=f\frac{Y}{Z}\) |