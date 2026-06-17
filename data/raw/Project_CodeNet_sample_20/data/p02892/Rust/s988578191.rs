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

#[allow(unused_macros)]
macro_rules! p {
    ([$($x:expr), *]) => {{
        let mut f = true;
        $(
            print!("{}{}", if f {""} else {" "}, $x);
            f = false;
        )*
78786    print!("\n");
    }};
    ($x:expr) => {{
        let mut f = true;
        for a in $x.iter() {
            print!("{}{}", if f {""} else {" "}, a);
            f = false;
        }
        print!("\n");
    }};
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

#[allow(dead_code)]
fn vector_accumulation(vec: &Vec<i64>) -> Vec<i64> {
    let mut res = Vec::new();
    let size = vec.len();
    res.push(0);
    for i in 0..size {
        res.push(vec[i]);
    }
    for i in 0..size {
        res[i + 1] += res[i];
    }
    res
}

#[allow(dead_code)]
pub fn gcd(mut a: i64, mut b: i64) -> i64 {
    if (a < b) {
        let t = a;
        a = b;
        b = t;
    }
    if b == 0 {
        a
    } else {
        gcd(b, a % b)
    }
}

#[allow(dead_code)]
pub fn bipartite_matching(g: &[Vec<usize>]) -> usize {
    fn dfs(
        v: usize,
        g: &[Vec<usize>],
        mat: &mut [Option<usize>],
        used: &mut [usize],
        id: usize,
    ) -> bool {
        used[v] = id;
        for &u in &g[v] {
            if mat[u].is_none()
                || used[mat[u].unwrap()] != id && dfs(mat[u].unwrap(), g, mat, used, id)
            {
                mat[v] = Some(u);
                mat[u] = Some(v);
                return true;
            }
        }
        false
    }
    let mut res = 0;
    let mut mat = vec![None; g.len()];
    let mut used = vec![0; g.len()];
    for v in 0..g.len() {
        if mat[v].is_none() && dfs(v, g, &mut mat, &mut used, v + 1) {
            res += 1;
        }
    }
    res
}

fn bipartiate_graph_judgement(
    v: usize,
    c: i64,
    color: &mut Vec<i64>,
    graph: &Vec<Vec<usize>>,
) -> bool {
    color[v] = c;
    // println!("{:?}", c);
    for nv in graph[v].iter() {
        if color[*nv] != -1 {
            if color[*nv] == c {
                return false;
            };

            continue;
        }
        if !bipartiate_graph_judgement(*nv, 1 - c, color, &graph) {
            return false;
        }
    }

    true
}

fn warshall_floyd(graph: &Vec<Vec<usize>>) -> Vec<Vec<usize>> {
    let n = graph.len();
    let mut res: Vec<Vec<usize>> =
        vec![vec![INF as usize; (graph.len()) as usize]; (graph.len()) as usize];
    for i in 0..n {
        res[i][i] = 0;
    }
    for i in 0..n {
        for v in graph[i].iter() {
            res[i][*v] = 1;
        }
    }
    for k in 0..n {
        for i in 0..n {
            for j in 0..n {
                res[i][j] = min(res[i][j], res[i][k] + res[k][j]);
            }
        }
    }
    res
}

fn solve() {
    let n: usize = read();
    let mut vv: Vec<Vec<i64>> = vec![vec![0; (n) as usize]; (n) as usize];
    for i in 0..n {
        let s: String = read();
        let mut va = s.as_bytes().to_vec();
        for j in 0..n {
            vv[i][j] = va[j] as i64 - '0' as i64;
        }
    }

    let mut graph: Vec<Vec<usize>> = vec![vec![0; (0) as usize]; (n) as usize];
    for i in 0..n {
        for j in 0..n {
            if (vv[i][j] == 1) {
                graph[i].push(j);
            }
        }
    }
    // println!("{:?}", graph);
    let mut color: Vec<i64> = vec![-1; n];
    let flg = bipartiate_graph_judgement(0, 0, &mut color, &graph);
    // println!("{:?}", color);
    if flg == false {
        println!("-1");
    } else {
        let r = warshall_floyd(&graph);
        let mut res = 0;
        for i in 0..n {
            for j in 0..n {
                if (r[i][j] == INF as usize) {
                    continue;
                }
                res = max(res, r[i][j]);
            }
        }
        println!("{}", res + 1);
    }

    return;
}
fn main() {
    solve()
}
