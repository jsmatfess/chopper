	.def	@feat.00;
	.scl	3;
	.type	0;
	.endef
	.globl	@feat.00
@feat.00 = 0
	.att_syntax
	.file	"quote_detection.3378b551ff5056db-cgu.0"
	.def	quoted_field;
	.scl	2;
	.type	32;
	.endef
	.section	.text,"xr",one_only,quoted_field,unique,0
	.globl	quoted_field
	.p2align	4
quoted_field:
.seh_proc quoted_field
	pushq	%rsi
	.seh_pushreg %rsi
	pushq	%rbx
	.seh_pushreg %rbx
	.seh_endprologue
	testq	%rdx, %rdx
	je	.LBB0_14
	addq	%rcx, %rdx
	.p2align	4
.LBB0_2:
	cmpq	%rdx, %rcx
	setne	%al
	je	.LBB0_13
	movzbl	(%rcx), %ebx
	movzbl	%bl, %r10d
	testb	%r10b, %r10b
	js	.LBB0_5
	incq	%rcx
	cmpl	$10, %r10d
	jne	.LBB0_10
	jmp	.LBB0_13
	.p2align	4
.LBB0_5:
	movl	%r10d, %r11d
	andl	$31, %r11d
	movzbl	1(%rcx), %esi
	andl	$63, %esi
	cmpb	$-33, %r10b
	jbe	.LBB0_8
	movzbl	2(%rcx), %r10d
	shll	$6, %esi
	andl	$63, %r10d
	orl	%esi, %r10d
	cmpb	$-16, %bl
	jb	.LBB0_9
	movzbl	3(%rcx), %esi
	addq	$4, %rcx
	andl	$7, %r11d
	shll	$18, %r11d
	shll	$6, %r10d
	andl	$63, %esi
	orl	%r10d, %esi
	orl	%r11d, %esi
	movl	%esi, %r10d
	cmpl	$10, %r10d
	jne	.LBB0_10
	jmp	.LBB0_13
.LBB0_8:
	addq	$2, %rcx
	shll	$6, %r11d
	orl	%esi, %r11d
	movl	%r11d, %r10d
	cmpl	$10, %r10d
	jne	.LBB0_10
	jmp	.LBB0_13
.LBB0_9:
	addq	$3, %rcx
	shll	$12, %r11d
	orl	%r11d, %r10d
	cmpl	$10, %r10d
	je	.LBB0_13
	.p2align	4
.LBB0_10:
	cmpl	$13, %r10d
	je	.LBB0_13
	cmpl	%r10d, %r8d
	je	.LBB0_13
	cmpl	%r10d, %r9d
	jne	.LBB0_2
.LBB0_13:
	.seh_startepilogue
	popq	%rbx
	popq	%rsi
	.seh_endepilogue
	retq
.LBB0_14:
	movb	$1, %al
	.seh_startepilogue
	popq	%rbx
	popq	%rsi
	.seh_endepilogue
	retq
	.seh_endproc

	.def	quoted_field_default;
	.scl	2;
	.type	32;
	.endef
	.section	.text,"xr",one_only,quoted_field_default,unique,1
	.globl	quoted_field_default
	.p2align	4
quoted_field_default:
.seh_proc quoted_field_default
	pushq	%rsi
	.seh_pushreg %rsi
	.seh_endprologue
	testq	%rdx, %rdx
	je	.LBB1_1
	addq	%rcx, %rdx
	movabsq	$17609365922816, %r8
	.p2align	4
.LBB1_3:
	cmpq	%rdx, %rcx
	setne	%al
	je	.LBB1_13
	movzbl	(%rcx), %r11d
	movzbl	%r11b, %r9d
	testb	%r9b, %r9b
	js	.LBB1_6
	incq	%rcx
	cmpl	$44, %r9d
	jbe	.LBB1_12
	jmp	.LBB1_3
	.p2align	4
.LBB1_6:
	movl	%r9d, %r10d
	andl	$31, %r10d
	movzbl	1(%rcx), %esi
	andl	$63, %esi
	cmpb	$-33, %r9b
	jbe	.LBB1_7
	movzbl	2(%rcx), %r9d
	shll	$6, %esi
	andl	$63, %r9d
	orl	%esi, %r9d
	cmpb	$-16, %r11b
	jb	.LBB1_9
	movzbl	3(%rcx), %r11d
	addq	$4, %rcx
	andl	$7, %r10d
	shll	$18, %r10d
	shll	$6, %r9d
	andl	$63, %r11d
	orl	%r9d, %r11d
	orl	%r10d, %r11d
	movl	%r11d, %r9d
	cmpl	$44, %r9d
	jbe	.LBB1_12
	jmp	.LBB1_3
.LBB1_7:
	addq	$2, %rcx
	shll	$6, %r10d
	orl	%esi, %r10d
	movl	%r10d, %r9d
	cmpl	$44, %r9d
	jbe	.LBB1_12
	jmp	.LBB1_3
.LBB1_9:
	addq	$3, %rcx
	shll	$12, %r10d
	orl	%r10d, %r9d
	cmpl	$44, %r9d
	ja	.LBB1_3
	.p2align	4
.LBB1_12:
	movl	%r9d, %r9d
	btq	%r9, %r8
	jae	.LBB1_3
.LBB1_13:
	.seh_startepilogue
	popq	%rsi
	.seh_endepilogue
	retq
.LBB1_1:
	movb	$1, %al
	.seh_startepilogue
	popq	%rsi
	.seh_endepilogue
	retq
	.seh_endproc

