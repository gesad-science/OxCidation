// -*- coding:utf-8-unix -*-

use std::cmp::*;
use std::collections::*;
use std::fs::File;
use std::io::prelude::*;
use std::io::*;
use std::vec;

const INF: i64 = 1223372036854775807;
const MEM_SIZE: usize = 202020;
const MOD: i64 = 1000000007;
use std::cmp::*;
use std::collections::*;
use std::io::stdin;
use std::io::stdout;
use std::io::Write;
#[allow(dead_code)]
fn read<T: std::str::FromStr>() -> T {
    let mut s = String::new();
    std::io::stdin().read_line(&mut s).ok();
    s.trim().parse().ok().unwrap()
}
#[allow(dead_code)]
fn read_vec<T: std::str::FromStr>() -> Vec<T> {
    read::<String>()
        .split_whitespace()
        .map(|e| e.parse().ok().unwrap())
        .collect()
}
#[allow(dead_code)]
fn read_vec2<T: std::str::FromStr>(n: u32) -> Vec<Vec<T>> {
    (0..n).map(|_| read_vec()).collect()
}

#[allow(dead_code)]
fn readii() -> (i64, i64) {
    let mut str = String::new();
    let _ = stdin().read_line(&mut str).unwrap();
    let mut iter = str.split_whitespace();
    (
        iter.next().unwrap().parse::<i64>().unwrap(),
        iter.next().unwrap().parse::<i64>().unwrap(),
    )
}
#[allow(dead_code)]
fn readuu() -> (usize, usize) {
    let mut str = String::new();
    let _ = stdin().read_line(&mut str).unwrap();
    let mut iter = str.split_whitespace();
    (
        iter.next().unwrap().parse::<usize>().unwrap(),
        iter.next().unwrap().parse::<usize>().unwrap(),
    )
}

#[allow(dead_code)]
fn readuuu() -> (usize, usize, usize) {
    let mut str = String::new();
    let _ = stdin().read_line(&mut str).unwrap();
    let mut iter = str.split_whitespace();
    (
        iter.next().unwrap().parse::<usize>().unwrap(),
        iter.next().unwrap().parse::<usize>().unwrap(),
        iter.next().unwrap().parse::<usize>().unwrap(),
    )
}

#[allow(unused_macros)]
macro_rules! debug {
    ($($e:expr),*) => {
        #[cfg(debug_assertions)]
        $({
            let (e, mut err) = (stringify!($e), std::io::stderr());
            writeln!(err, "{} = {:?}", e, $e).unwrap()
        })*
    };
}

fn solve() {
    let (n, k) = readuu();
    let m = (n) * (n - 1) / 2 - (n - 1);
    if (k > m) {
        println!("-1");
        return;
    }
    println!("{:?}", n - 1 + m - k);
    for i in 0..n - 1 {
        println!("{} {}", 1, i + 2);
    }
    let mut data: Vec<(usize, usize)> = vec![(0, 0); 0];
    for i in 1..n {
        for j in i + 1..n {
            data.push((i + 1, j + 1));
        }
    }
    data.sort();
    for i in 0..(m - k) {
        println!("{} {} ", data[i].0, data[i].1);
    }

    return;
}
fn main() {
    solve()
}
